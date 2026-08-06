"""Materialize an exact, disposable view of the Git index."""

import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from prec.errors.errors import RepositoryError
from prec.git.repository import Repository


@dataclass(frozen=True, slots=True)
class IndexSnapshot:
    root: Path
    environment: Mapping[str, str]
    repository: Repository


@contextmanager
def index_snapshot(repository: Repository) -> Iterator[IndexSnapshot]:
    parent = repository.git_dir / "prec" / "tmp"
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="snapshot-", dir=parent))
    root = temporary / "worktree"
    copied_index = temporary / "index"
    root.mkdir()
    try:
        environment = {
            "GIT_DIR": os.fspath(repository.git_dir),
            "GIT_WORK_TREE": os.fspath(root),
            "GIT_INDEX_FILE": os.fspath(copied_index),
        }
        snapshot_repository = Repository(
            root=repository.root,
            git_dir=repository.git_dir,
            index_path=copied_index,
            environment=environment,
        )
        try:
            shutil.copy2(repository.index_path, copied_index)
        except FileNotFoundError:
            snapshot_repository.git(["read-tree", "--empty"])
        except OSError as error:
            raise RepositoryError(f"could not copy Git index: {error}") from error

        prefix = os.fspath(root) + os.sep
        snapshot_repository.git(["checkout-index", "--all", "--force", f"--prefix={prefix}"])
        yield IndexSnapshot(root=root, environment=environment, repository=snapshot_repository)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
