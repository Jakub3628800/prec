import os
from pathlib import Path

import pytest
from conftest import commit_all, git

from prec.errors.errors import RepositoryError
from prec.git.candidates import Source, candidates
from prec.git.repository import Repository


def discovered(repo: Path, source: Source) -> tuple[str, ...]:
    return candidates(Repository.discover(repo), source)


def test_changed_clean_modified_untracked_and_ignored(repo: Path) -> None:
    (repo / ".gitignore").write_text("ignored.txt\n")
    (repo / "tracked.txt").write_text("old")
    commit_all(repo)
    assert discovered(repo, Source.CHANGED) == ()

    (repo / "tracked.txt").write_text("new")
    (repo / "new.txt").write_text("new")
    (repo / "ignored.txt").write_text("ignored")
    assert discovered(repo, Source.CHANGED) == ("new.txt", "tracked.txt")


def test_all_includes_unchanged_and_excludes_deleted(repo: Path) -> None:
    (repo / "a.txt").write_text("a")
    (repo / "b.txt").write_text("b")
    commit_all(repo)
    (repo / "b.txt").unlink()
    (repo / "c.txt").write_text("c")
    assert discovered(repo, Source.ALL) == ("a.txt", "c.txt")


def test_staged_only_and_rename_target(repo: Path) -> None:
    (repo / "a.txt").write_text("a")
    (repo / "unstaged.txt").write_text("old")
    commit_all(repo)
    git(repo, "mv", "a.txt", "renamed.txt")
    (repo / "unstaged.txt").write_text("new")
    assert discovered(repo, Source.STAGED) == ("renamed.txt",)
    assert discovered(repo, Source.CHANGED) == ("renamed.txt", "unstaged.txt")


def test_unborn_repository(repo: Path) -> None:
    (repo / "indexed.txt").write_text("indexed")
    (repo / "untracked.txt").write_text("untracked")
    git(repo, "add", "indexed.txt")
    assert discovered(repo, Source.STAGED) == ("indexed.txt",)
    assert discovered(repo, Source.CHANGED) == ("indexed.txt", "untracked.txt")


def test_nul_delimited_path_fidelity(repo: Path) -> None:
    names = ["-leading", "has space", "has\ttab", "has\nnewline", "héllo"]
    for name in names:
        (repo / name).write_text(name)
    assert discovered(repo, Source.CHANGED) == tuple(
        sorted(names, key=lambda name: name.encode("utf-8"))
    )


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlinks")
def test_symlink_is_candidate(repo: Path) -> None:
    (repo / "target").write_text("target")
    os.symlink("target", repo / "link")
    git(repo, "add", "link")
    assert discovered(repo, Source.STAGED) == ("link",)


@pytest.mark.skipif(os.name != "posix", reason="invalid byte paths are a Unix behavior")
def test_invalid_utf8_path_is_error(repo: Path) -> None:
    root = os.fsencode(repo)
    descriptor = os.open(root + b"/bad-\xff", os.O_WRONLY | os.O_CREAT, 0o644)
    os.close(descriptor)
    with pytest.raises(RepositoryError, match="not valid UTF-8"):
        discovered(repo, Source.CHANGED)
