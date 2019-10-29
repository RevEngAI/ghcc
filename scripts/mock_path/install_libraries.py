#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
import tempfile

import ghcc

parser = argparse.ArgumentParser()
parser.add_argument("file", type=str)  # path to libraries log file
args = parser.parse_args()


def skip_until(elem, iterator):
    flag = False
    for x in iterator:
        if x == elem:
            flag = True
        if flag:
            yield x


def main():
    with open(args.file) as f:
        libraries = f.read().split()

    # Create a dummy .C file for compilation / linking.
    tempdir = tempfile.TemporaryDirectory()
    src_path = os.path.join(tempdir.name, "main.c")
    with open(src_path, "w") as f:
        f.write(r"""
#include <stdio.h>
int main() {
    printf("Hello world!\n");
    return 0;
}""")

    def check_installed(_library: str) -> bool:
        try:
            _ret = ghcc.utils.run_command(["gcc", src_path, f"-l{_library}"], cwd=tempdir.name)
            return _ret.return_code == 0
        except subprocess.CalledProcessError:
            return False

    packages_to_install = []
    ghcc.utils.run_command(["apt-get", "update"])  # refresh package index just in case

    for lib in libraries:
        # Check if library is installed -- whether linking succeeds.
        if check_installed(lib):
            ghcc.log(f"'{lib}' is installed", "info")
            continue

        # Find the correct package for the name:
        # 1. Enumerate different package names.
        # 2. Search for the package with `apt search`.
        # 3. Install the package.
        # 4. Retry compilation to see if it succeeds.
        libname = lib.replace("_", "[-_]")
        names = [f"lib{libname}-dev",
                 f"lib{libname}(-?[0-9.]+)?-dev",
                 f"lib{libname}(-?[0-9.]+)?",
                 f"{libname}(-?[0-9.]+)?-dev",
                 libname]
        for name in names:
            ret = ghcc.utils.run_command(["apt-cache", "search", "--quiet", name], timeout=10, return_output=True)
            packages = [line.split()[0] for line in ret.captured_output.decode('utf-8').split('\n') if line]
            if len(packages) > 0:
                package = packages[0]
                ret = ghcc.utils.run_command(["apt-get", "install", "--dry-run", package], return_output=True)
                match = re.search(r"(\d+) newly installed", ret.captured_output.decode('utf-8'))
                if match.group(1):
                    install_count = int(match.group(1))
                    if install_count > 50:
                        # Too much to install, ignore.
                        continue
                try:
                    # Do not use a timeout, otherwise DPKG will break.
                    ret = ghcc.utils.run_command(["apt-get", "install", "-y", "--no-install-recommends", package])
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                    ghcc.log(f"Exception occurred when installing '{package}' for '{lib}': {e}", "error")
                    continue
                if ret.return_code != 0 or not check_installed(lib):
                    continue

                packages_to_install.append(package)
                ghcc.log(f"'{lib}' resolved to '{package}'", "success")
                break
        else:
            ghcc.log(f"Failed to resolve '{lib}'", "error")

    ghcc.log(f"Packages to install are:\n" + '\n'.join(packages_to_install), "info")


if __name__ == '__main__':
    main()
