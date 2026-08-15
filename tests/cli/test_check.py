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


def test_add_command_preserves_comments_and_exact_argv(repo: Path) -> None:
    config_path = repo / ".prec/prec-config.toml"
    config_path.write_text("# project checks\nversion = 1\n\nchecks = [] # keep this comment\n")

    result = run_prec(
        repo,
        "check",
        "add",
        "ruff",
        "--files",
        "*.py",
        "--exclude",
        "vendor/",
        "--",
        "ruff",
        "check",
        "--",
    )

    assert result.returncode == 0, result.stderr
    content = config_path.read_text()
    assert "# project checks" in content
    assert "# keep this comment" in content
    check = load_worktree_config(repo).checks[0]
    assert check.id == "ruff"
    assert check.run == ("ruff", "check", "--")
    assert check.files == ("*.py",)
    assert check.exclude == ("vendor/",)


def test_check_list_supports_nested_discovery_and_verbose_output(repo: Path) -> None:
    added = run_prec(repo, "check", "add", "truth", "--", "true")
    assert added.returncode == 0, added.stderr
    nested = repo / "one" / "two"
    nested.mkdir(parents=True)

    plain = run_prec(nested, "check", "list")
    verbose = run_prec(nested, "check", "list", "--verbose")

    assert plain.stdout == "truth\n"
    assert verbose.stdout == "truth\ttrue\n"


def test_edit_updates_selected_fields_and_preserves_other_content(repo: Path) -> None:
    config_path = repo / ".prec/prec-config.toml"
    config_path.write_text(
        "# heading\nversion = 1\n\n"
        "[[checks]]\n"
        'id = "lint" # identity\n'
        'run = ["old"]\n'
        'files = ["*.py"]\n'
        'exclude = ["vendor/"]\n'
    )

    result = run_prec(
        repo,
        "check",
        "edit",
        "lint",
        "--add-files",
        "*.pyi",
        "--clear-exclude",
        "--no-pass-filenames",
        "--timeout-seconds",
        "12.5",
        "--",
        "ruff",
        "check",
        "--",
    )

    assert result.returncode == 0, result.stderr
    content = config_path.read_text()
    assert "# heading" in content
    assert "# identity" in content
    check = load_worktree_config(repo).checks[0]
    assert check.run == ("ruff", "check", "--")
    assert check.files == ("*.py", "*.pyi")
    assert check.exclude == ()
    assert check.pass_filenames is False
    assert check.timeout_seconds == 12.5


def test_edit_rejects_noop_and_conflicting_list_operations(repo: Path) -> None:
    added = run_prec(repo, "check", "add", "truth", "--", "true")
    assert added.returncode == 0, added.stderr
    config_path = repo / ".prec/prec-config.toml"
    before = config_path.read_bytes()

    noop = run_prec(repo, "check", "edit", "truth")
    conflict = run_prec(
        repo,
        "check",
        "edit",
        "truth",
        "--files",
        "*.py",
        "--add-files",
        "*.pyi",
    )

    assert noop.returncode == 2
    assert "no changes requested" in noop.stderr
    assert conflict.returncode == 2
    assert "choose only one operation" in conflict.stderr
    assert config_path.read_bytes() == before


def test_remove_keeps_script_by_default_and_deletes_only_when_requested(repo: Path) -> None:
    first = run_prec(repo, "check", "add", "keep", "--custom", "python")
    assert first.returncode == 0, first.stderr
    kept_script = repo / ".prec/checks/keep/keep.py"

    removed = run_prec(repo, "check", "remove", "keep")

    assert removed.returncode == 0, removed.stderr
    assert kept_script.is_file()
    assert load_worktree_config(repo).checks == ()

    second = run_prec(repo, "check", "add", "discard", "--custom", "bash")
    assert second.returncode == 0, second.stderr
    discarded_script = repo / ".prec/checks/discard/discard.sh"

    deleted = run_prec(repo, "check", "remove", "discard", "--delete-script")

    assert deleted.returncode == 0, deleted.stderr
    assert not discarded_script.exists()
    assert "Deleted .prec/checks/discard/discard.sh" in deleted.stdout


def test_suggest_reports_detected_unconfigured_checks_without_writing(repo: Path) -> None:
    config_path = repo / ".prec/prec-config.toml"
    config_path.write_text("version = 1\nchecks = []\n")
    (repo / "pyproject.toml").write_text("[tool.ruff]\n[tool.pytest.ini_options]\n")
    before = config_path.read_bytes()

    result = run_prec(repo, "check", "suggest")

    assert result.returncode == 0, result.stderr
    assert "ruff\tRuff configuration detected" in result.stdout
    assert "tests\tpytest configuration detected" in result.stdout
    assert "prec check add ruff --files '*.py' -- ruff check --" in result.stdout
    assert config_path.read_bytes() == before
