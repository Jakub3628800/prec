import os
from pathlib import Path

import pytest
from conftest import commit_all, git, run_prec

from prec.config import load_worktree_config


@pytest.mark.parametrize(
    ("language", "extension", "marker"),
    [
        ("python", "py", "def check(filenames"),
        ("bash", "sh", 'local -a filenames=("$@")'),
    ],
)
def test_add_scaffolds_registers_and_runs_executable_check(
    repo: Path, language: str, extension: str, marker: str
) -> None:
    config_path = repo / ".prec/prec-config.toml"
    config_path.write_text("version = 1\nchecks = []\n")
    config_path.chmod(0o640)

    result = run_prec(
        repo,
        "check",
        "add",
        "sample-check",
        "--language",
        language,
        "--files",
        "*.txt",
    )

    relative = f".prec/checks/sample-check/sample_check.{extension}"
    script = repo / relative
    assert result.returncode == 0, result.stderr
    assert f"Created {relative}" in result.stdout
    assert marker in script.read_text()
    assert os.access(script, os.X_OK)
    assert config_path.stat().st_mode & 0o777 == 0o640
    assert load_worktree_config(repo).checks[0].run is None
    assert load_worktree_config(repo).checks[0].script == relative
    assert load_worktree_config(repo).checks[0].files == ("*.txt",)

    (repo / "-example.txt").write_text("content\n")
    executed = run_prec(repo, "run", "sample-check")
    assert executed.returncode == 0, executed.stderr
    assert "passed (exit code: 0)" in executed.stdout


def test_add_creates_config_and_derives_path_from_id(repo: Path) -> None:
    result = run_prec(repo, "check", "add", "no_tabs")

    assert result.returncode == 0, result.stderr
    script = repo / ".prec/checks/no_tabs/no_tabs.py"
    assert script.is_file()
    check = load_worktree_config(repo).checks[0]
    assert check.id == "no_tabs"
    assert check.run is None
    assert check.script == ".prec/checks/no_tabs/no_tabs.py"


def test_add_refuses_invalid_and_existing_checks(repo: Path) -> None:
    invalid = run_prec(repo, "check", "add", "Not.Valid")
    assert invalid.returncode == 2
    assert "check id must match" in invalid.stderr

    first = run_prec(repo, "check", "add", "duplicate")
    second = run_prec(repo, "check", "add", "duplicate")
    assert first.returncode == 0, first.stderr
    assert second.returncode == 2
    assert "already exists" in second.stderr


def test_custom_check_reports_missing_executable(repo: Path) -> None:
    config_path = repo / ".prec/prec-config.toml"
    config_path.write_text(
        'version = 1\n[[checks]]\nid = "missing"\nscript = ".prec/checks/missing.py"\n'
        "always_run = true\n"
    )
    missing = run_prec(repo, "run")
    assert missing.returncode == 2
    assert "custom check script not found" in missing.stderr


def test_add_refuses_opposite_language_orphan(repo: Path) -> None:
    bash = repo / ".prec/checks/collision/collision.sh"
    bash.parent.mkdir(parents=True)
    bash.write_text("#!/usr/bin/env bash\nexit 0\n")
    result = run_prec(repo, "check", "add", "collision")
    assert result.returncode == 2
    assert "custom check path already exists" in result.stderr


def test_generated_check_executes_from_staged_snapshot(repo: Path) -> None:
    added = run_prec(repo, "check", "add", "indexed", "--files", "*.txt")
    assert added.returncode == 0, added.stderr
    (repo / "base.txt").write_text("base\n")
    commit_all(repo)

    script = repo / ".prec/checks/indexed/indexed.py"
    script.write_text(script.read_text().replace("return 0", "return 9", 1))
    (repo / "staged.txt").write_text("staged\n")
    git(repo, "add", "staged.txt")
    result = run_prec(repo, "run", "--staged", "indexed")

    assert result.returncode == 0, result.stderr
    assert "passed (exit code: 0)" in result.stdout
