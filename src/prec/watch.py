"""Repository state observation for watch mode."""

import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from prec.config import CONFIG_PATH
from prec.errors import PrecError, RepositoryError
from prec.git.candidates import Source, candidates
from prec.git.repository import Repository

_POLL_INTERVAL_SECONDS = 0.5


@dataclass(frozen=True, slots=True)
class FileStamp:
    """Metadata used to notice changes without reading complete files."""

    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    inode: int


@dataclass(frozen=True, slots=True)
class WorktreeState:
    """Observable state for changed and all-file sources."""

    files: tuple[tuple[str, FileStamp | None], ...]


@dataclass(frozen=True, slots=True)
class StagedState:
    """Semantic state of the index and its comparison revision."""

    head: bytes
    index_digest: bytes


WatchState = WorktreeState | StagedState
ErrorCallback = Callable[[PrecError], None]
Observer = Callable[[], WatchState]
Sleeper = Callable[[float], None]


def _file_stamp(repository: Repository, path: str) -> FileStamp | None:
    try:
        stat = os.lstat(repository.root / path)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise RepositoryError(f"cannot inspect {path}: {error}") from error
    return FileStamp(
        mode=stat.st_mode,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        ctime_ns=stat.st_ctime_ns,
        inode=stat.st_ino,
    )


def observe(repository: Repository, source: Source) -> WatchState:
    """Return the repository state relevant to a watched source."""
    if source is Source.STAGED:
        head = repository.git(["rev-parse", "--verify", "HEAD"]) if repository.has_head() else b""
        index = repository.git(["ls-files", "--stage", "-z"])
        return StagedState(head=head, index_digest=hashlib.sha256(index).digest())

    paths = set(candidates(repository, source))
    paths.add(CONFIG_PATH)
    ordered = sorted(paths, key=lambda path: path.encode("utf-8"))
    return WorktreeState(tuple((path, _file_stamp(repository, path)) for path in ordered))


def wait_for_stable_change(
    observer: Observer,
    baseline: WatchState,
    *,
    on_error: ErrorCallback,
    interval_seconds: float = _POLL_INTERVAL_SECONDS,
    sleep: Sleeper = time.sleep,
) -> WatchState:
    """Wait until an observed change remains stable for one polling interval."""
    pending: WatchState | None = None
    reported_error: str | None = None
    while True:
        sleep(interval_seconds)
        try:
            current = observer()
        except PrecError as error:
            message = str(error)
            if message != reported_error:
                on_error(error)
                reported_error = message
            pending = None
            continue

        reported_error = None
        if current == baseline:
            pending = None
        elif current == pending:
            return current
        else:
            pending = current
