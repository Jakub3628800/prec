"""Git-aware candidate file discovery."""

import os
from enum import Enum

from prec.errors.errors import RepositoryError
from prec.git.repository import Repository


class Source(Enum):
    CHANGED = "changed"
    ALL = "all"
    STAGED = "staged"


def _decode_paths(output: bytes) -> set[str]:
    paths: set[str] = set()
    for raw in output.split(b"\0"):
        if not raw:
            continue
        try:
            paths.add(raw.decode("utf-8"))
        except UnicodeDecodeError as error:
            raise RepositoryError("selected repository path is not valid UTF-8") from error
    return paths


def _sorted(paths: set[str]) -> tuple[str, ...]:
    return tuple(sorted(paths, key=lambda path: path.encode("utf-8")))


def _existing_worktree_paths(repository: Repository, paths: set[str]) -> set[str]:
    result: set[str] = set()
    for path in paths:
        absolute = repository.root / path
        if not os.path.lexists(absolute):
            continue
        if absolute.is_dir() and not absolute.is_symlink():
            continue
        result.add(path)
    return result


def _index_regular_paths(repository: Repository) -> set[str]:
    output = repository.git(["ls-files", "--stage", "-z"])
    paths: set[str] = set()
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, _object_id, stage = metadata.split()
        except ValueError as error:
            raise RepositoryError("git returned an invalid index entry") from error
        if stage != b"0" or mode == b"160000":
            continue
        try:
            paths.add(raw_path.decode("utf-8"))
        except UnicodeDecodeError as error:
            raise RepositoryError("selected repository path is not valid UTF-8") from error
    return paths


def candidates(repository: Repository, source: Source) -> tuple[str, ...]:
    if source is Source.STAGED:
        if repository.has_head():
            changed = _decode_paths(
                repository.git(
                    [
                        "diff",
                        "--cached",
                        "--name-only",
                        "-z",
                        "--diff-filter=ACMRT",
                        "HEAD",
                        "--",
                    ]
                )
            )
        else:
            changed = _index_regular_paths(repository)
        return _sorted(changed & _index_regular_paths(repository))

    if source is Source.ALL:
        discovered = _decode_paths(
            repository.git(["ls-files", "--cached", "--others", "--exclude-standard", "-z"])
        )
        return _sorted(_existing_worktree_paths(repository, discovered))

    if repository.has_head():
        tracked = _decode_paths(
            repository.git(["diff", "--name-only", "-z", "--diff-filter=ACMRT", "HEAD", "--"])
        )
    else:
        tracked = _decode_paths(repository.git(["ls-files", "--cached", "-z"]))
    untracked = _decode_paths(repository.git(["ls-files", "--others", "--exclude-standard", "-z"]))
    return _sorted(_existing_worktree_paths(repository, tracked | untracked))
