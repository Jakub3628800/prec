"""Generic access to Git index entries and blobs."""

from dataclasses import dataclass

from prec.errors import RepositoryError
from prec.git.repository import Repository


@dataclass(frozen=True, slots=True)
class IndexEntry:
    mode: str
    object_id: str
    stage: int
    path: str


def index_entries(repository: Repository, path: str) -> tuple[IndexEntry, ...]:
    """Return all index stages for one repository-relative path."""
    output = repository.git(["ls-files", "--stage", "-z", "--", path])
    entries: list[IndexEntry] = []
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            raw_mode, raw_object_id, raw_stage = metadata.split()
            entry = IndexEntry(
                mode=raw_mode.decode("ascii"),
                object_id=raw_object_id.decode("ascii"),
                stage=int(raw_stage),
                path=raw_path.decode("utf-8"),
            )
        except (UnicodeDecodeError, ValueError) as error:
            raise RepositoryError("git returned an invalid index entry") from error
        entries.append(entry)
    return tuple(entries)


def read_index_blob(repository: Repository, path: str) -> bytes:
    """Read a stage-zero blob from the index."""
    return repository.git(["show", f":{path}"])
