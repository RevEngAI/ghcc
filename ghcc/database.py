import sys
from datetime import datetime
from typing import List, Optional

import pymongo
from mypy_extensions import TypedDict

__all__ = [
    "RepoMakefileEntry",
    "RepoEntry",
    "Database",
]


class RepoMakefileEntry(TypedDict):
    directory: str  # directory containing the Makefile
    num_binaries: int  # number of binaries generated (required because MongoDB cannot aggregate list lengths)
    binaries: List[str]  # list of paths to binaries generated by make operation
    sha256: List[str]  # SHA256 hashes for each binary


class RepoEntry(TypedDict):
    repo_owner: str
    repo_name: str
    clone_successful: bool  # whether the repo has been successfully cloned to the server
    compiled: bool  # whether the repo has been tested for compilation
    num_makefiles: int  # number of compilable Makefiles (required because MongoDB cannot aggregate list lengths)
    makefiles: List[RepoMakefileEntry]  # list of Makefiles that are successfully compiled


class Database:
    r"""An abstraction over MongoDB that stores information about repositories.
    """
    HOST = "localhost"
    PORT = 27018
    AUTH_DB_NAME = "***REMOVED***"
    DB_NAME = "***REMOVED***"
    COLLECTION_NAME = "repos"
    # TODO: This is so stupid and so unsafe but I really don't know any better way :(
    USERNAME = "***REMOVED***"
    PASSWORD = "***REMOVED***"

    def __init__(self, username: Optional[str] = None, password: Optional[str] = None):
        r"""Create a connection to the database.
        """
        self.client = pymongo.MongoClient(
            self.HOST, port=self.PORT, authSource=self.AUTH_DB_NAME,
            username=username or self.USERNAME, password=password or self.PASSWORD)
        self.collection = self.client[self.DB_NAME][self.COLLECTION_NAME]

    def close(self) -> None:
        self.client.close()
        del self.collection

    def get(self, repo_owner: str, repo_name: str) -> Optional[RepoEntry]:
        r"""Get the DB entry corresponding to the specified repository.

        :return: If entry exists, it is returned as a dictionary; otherwise ``None`` is returned.
        """
        return self.collection.find_one({"repo_owner": repo_owner, "repo_name": repo_name})

    def add_repo(self, repo_owner: str, repo_name: str, clone_successful: bool,
                 clone_time: Optional[datetime] = None, repo_size: int = -1) -> None:
        r"""Add a new DB entry for the specified repository. Arguments correspond to the first three fields in
        :class:`RepoEntry`. Other fields are set to sensible default values (``False`` and ``[]``).

        :param repo_owner: Owner of the repository.
        :param repo_name: Name of the repository.
        :param clone_successful: Whether the repository was successfully cloned.
        :param clone_time: Time when cloning is performed.
        :param repo_size: Size (in bytes) of the cloned repository, or ``-1`` (default) if cloning failed.
        :return: The internal ID of the inserted entry.
        """
        if self.get(repo_owner, repo_name) is None:
            record = {
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "clone_successful": clone_successful,
                "repo_size": repo_size,
                "compiled": False,
                "num_makefiles": 0,
                "num_binaries": 0,
                "makefiles": [],
            }
            self.collection.insert_one(record)

    def update_makefile(self, repo_owner: str, repo_name: str, makefiles: List[RepoMakefileEntry]) -> None:
        entry = self.get(repo_owner, repo_name)
        if entry is None:
            raise ValueError(f"Specified repository {repo_owner}/{repo_name} does not exist")
        if len(entry["makefiles"]) not in [0, len(makefiles)]:
            raise ValueError(f"Number of makefiles stored in entry ({len(entry['makefiles'])}) does not "
                             f"match provided list ({len(makefiles)})")
        result = self.collection.update_one({"_id": entry["_id"]}, {"$set": {
            "compiled": True,
            "num_makefiles": len(makefiles),
            "num_binaries": sum(len(makefile["binaries"]) for makefile in makefiles),
            "makefiles": makefiles,
        }})
        assert result.matched_count == 1


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == "clear":
        confirm = input("This will drop the entire database. Confirm? [y/N]")
        if confirm.lower() in ["y", "yes"]:
            db = Database()
            db.collection.delete_many({})
            db.close()
            print("Database dropped.")
        else:
            print("Operation cancelled.")
