import functools
import multiprocessing
import subprocess
import sys
import tempfile
import threading
import types
from typing import Any, Dict, List, NamedTuple, Optional, TextIO, Type, TypeVar, Union

import psutil
import tenacity

from ghcc.logging import log

__all__ = [
    "Pool",
    "error_wrapper",
    "CommandResult",
    "run_command",
    "get_folder_size",
    "readable_size",
    "get_file_lines",
    "register_ipython_excepthook",
    "exception_wrapper",
    "to_dict",
    "to_namedtuple",
]


class Pool:
    r"""A wrapper over ``multiprocessing.Pool`` that uses single-threaded execution when :attr:`processes` is zero.
    """

    def __new__(cls, processes: int, *args, **kwargs):
        if processes > 0:
            return multiprocessing.Pool(processes, *args, **kwargs)
        return super().__new__(cls)  # return a mock Pool instance.

    def imap_unordered(self, fn, iterator):
        yield from map(fn, iterator)

    @staticmethod
    def _no_op(self, *args, **kwargs):
        pass

    def __getattr__(self, item):
        return types.MethodType(Pool._no_op, self)  # no-op for everything else


def _run_command_retry_logger(retry_state: tenacity.RetryCallState) -> None:
    args = retry_state.args[0] if len(retry_state.args) > 0 else retry_state.kwargs['args']
    if isinstance(args, list):
        args = ' '.join(args)
    cwd = retry_state.args[2] if len(retry_state.args) > 2 else retry_state.kwargs.get('cwd', None)
    msg = f"{retry_state.attempt_number} failed attempt(s) for command: '{args}'"
    if cwd is not None:
        msg += f" in working directory '{cwd}'"
    log(msg, "warning")


class CommandResult(NamedTuple):
    command: List[str]
    return_code: int
    captured_output: Optional[bytes]


def error_wrapper(err: Exception) -> Exception:
    r"""Wrap exceptions raised in `subprocess` to output captured output by default.
    """
    if not isinstance(err, (subprocess.CalledProcessError, subprocess.TimeoutExpired)):
        return err

    def __str__(self):
        string = super(self.__class__, self).__str__()
        if self.output:
            try:
                output = self.output.decode('utf-8')
            except UnicodeEncodeError:  # ignore output
                string += "\nFailed to parse output."
            else:
                string += "\nCaptured output:\n" + '\n'.join([f'\t{line}' for line in output.split('\n')])
        else:
            string += "\nNo output was generated."
        return string

    # Dynamically create a new type that overrides __str__, because replacing __str__ on instances don't work.
    err_type = type(err)
    new_type = type(err_type.__name__, (err_type,), {"__str__": __str__})

    err.__class__ = new_type
    return err


@tenacity.retry(retry=tenacity.retry_if_exception_type(OSError), reraise=True,
                stop=tenacity.stop_after_attempt(6),  # retry 5 times
                wait=tenacity.wait_random_exponential(multiplier=2, max=60),
                before_sleep=_run_command_retry_logger)
def run_command(args: Union[str, List[str]], env: Optional[Dict[bytes, bytes]] = None, cwd: Optional[str] = None,
                timeout: Optional[int] = None, return_output: bool = False, **kwargs) -> CommandResult:
    r"""A wrapper over ``subprocess.check_output`` that prevents deadlock caused by the combination of pipes and
    timeout. Output is redirected into a temporary file and returned only on exceptions.

    In case an OSError occurs, the function will retry for a maximum for 5 times with exponential backoff. If error
    still occurs, we just throw it up.

    :param args: The command to run. Should be either a `str` or a list of `str` depending on whether ``shell`` is True.
    :param env: Environment variables to set before running the command. Defaults to None.
    :param cwd: The working directory of the command to run. If None, uses the default (probably user home).
    :param timeout: Maximum running time for the command. If running time exceeds the specified limit,
        ``subprocess.TimeoutExpired`` is thrown.
    :param return_output: If ``True``, the captured output is returned. Otherwise, the return code is returned.
    """
    with tempfile.TemporaryFile() as f:
        try:
            ret = subprocess.run(args, check=True, stdout=f, stderr=subprocess.STDOUT,
                                 timeout=timeout, env=env, cwd=cwd, **kwargs)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            f.seek(0)
            e.output = f.read()
            raise error_wrapper(e) from None
        if return_output or ret.returncode != 0:
            f.seek(0)
            return CommandResult(args, ret.returncode, f.read())
    return CommandResult(args, ret.returncode, None)


def get_folder_size(path: str) -> int:
    r"""Get disk usage of given path in bytes.

    Credit: https://stackoverflow.com/a/25574638/4909228
    """
    return int(subprocess.check_output(['du', '-bs', path]).split()[0].decode('utf-8'))


def readable_size(size: int) -> str:
    r"""Represent file size in human-readable format.

    :param size: File size in bytes.
    """
    units = ["", "K", "M", "G", "T"]
    for unit in units:
        if size < 1024:
            return f"{size:.2f}{unit}"
        size /= 1024
    return f"{size:.2f}P"  # this won't happen


def get_file_lines(path: str) -> int:
    r"""Get number of lines in text file.
    """
    return int(subprocess.check_output(['wc', '-l', path]).decode('utf-8'))


def kill_proc_tree(pid: int, including_parent: bool = True) -> None:
    r"""Kill entire process tree.
    """
    parent = psutil.Process(pid)
    children = parent.children(recursive=True)
    for child in children:
        child.kill()
    gone, still_alive = psutil.wait_procs(children, timeout=5)
    if including_parent:
        parent.kill()
        parent.wait(5)


def register_ipython_excepthook() -> None:
    r"""Register an exception hook that launches an interactive IPython session upon uncaught exceptions.
    """

    def excepthook(type, value, traceback):
        if type is KeyboardInterrupt:
            # don't capture keyboard interrupts (Ctrl+C)
            sys.__excepthook__(type, value, traceback)
        else:
            ipython_hook(type, value, traceback)

    # enter IPython debugger on exception
    from IPython.core import ultratb

    ipython_hook = ultratb.FormattedTB(mode='Context', color_scheme='Linux', call_pdb=1)
    sys.excepthook = excepthook


def exception_wrapper(handler_fn):
    r"""Function decorator that calls the specified handler function when a exception occurs inside the decorated
    function.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                return handler_fn(e, *args, **kwargs)

        return wrapped

    return decorator


def to_dict(nm_tpl: NamedTuple) -> Dict[str, Any]:
    return {key: value for key, value in zip(nm_tpl._fields, nm_tpl)}


NamedTupleType = TypeVar('NamedTupleType', bound=NamedTuple)


def to_namedtuple(nm_tpl_type: Type[NamedTupleType], dic: Dict[str, Any]) -> NamedTupleType:
    return nm_tpl_type(**dic)


class MultiprocessingFileWriter(TextIO):
    """A multiprocessing file writer that allows multiple processes to write to the same file. Order is not guaranteed.

    This is very similar to :class:`~ghcc.logging.MultiprocessingFileHandler`.
    """

    def __init__(self, path: str, mode: str = "a"):
        self._file = open("path")
        self._queue = multiprocessing.Queue(-1)

        self._thread = threading.Thread(target=self._receive)
        self._thread.daemon = True
        self._thread.start()

    def __enter__(self) -> TextIO:
        return self._file

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._thread.join()
        self._file.close()

    def write(self, s: str):
        self._queue.put_nowait(s)

    def _receive(self):
        while True:
            try:
                record = self._queue.get()
                self._file.write(record)
            except EOFError:
                break
