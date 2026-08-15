import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from conftest import commit_all, config, git, run_prec


def test_list_and_nested_discovery(repo: Path) -> None:
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                '[[checks]]\nid = "first"\nrun = ["true"]',
                '[[checks]]\nid = "second"\nrun = ["true"]',
            ]
        )
    )
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)
    listed = run_prec(nested, "list")
    assert listed.returncode == 0
    assert listed.stdout == "first\nsecond\n"


def test_bare_prec_selects_changed_and_untracked_files(repo: Path) -> None:
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                """[[checks]]
id = "capture"
run = ["python3", "-c", "import sys; open('captured.txt', 'w').write('|'.join(sys.argv[1:]))"]
files = ["*.py"]"""
            ]
        )
    )
    (repo / "old.py").write_text("old")
    (repo / "ignored.py").write_text("ignored")
    (repo / ".gitignore").write_text("ignored.py\n")
    commit_all(repo)
    (repo / "old.py").write_text("changed")
    (repo / "new.py").write_text("new")
    result = run_prec(repo)
    assert result.returncode == 0
    assert (repo / "captured.txt").read_text() == "new.py|old.py"
    assert "capture" in result.stdout
    assert "passed (exit code: 0)" in result.stdout


def test_all_includes_unchanged_files(repo: Path) -> None:
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                """[[checks]]
id = "capture"
run = ["python3", "-c", "import sys; open('captured.txt', 'w').write('|'.join(sys.argv[1:]))"]
files = ["*.txt"]"""
            ]
        )
    )
    (repo / "unchanged.txt").write_text("x")
    commit_all(repo)
    result = run_prec(repo, "run", "--all")
    assert result.returncode == 0
    assert (repo / "captured.txt").read_text() == "unchanged.txt"


def test_staged_reads_exact_index_content_and_cleans_snapshot(repo: Path) -> None:
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                """[[checks]]
id = "content"
run = ["python3", "-c", "assert open('data.txt').read() == 'staged'"]
files = ["data.txt"]
pass_filenames = false"""
            ]
        )
    )
    (repo / "data.txt").write_text("base")
    commit_all(repo)
    (repo / "data.txt").write_text("staged")
    git(repo, "add", "data.txt")
    (repo / "data.txt").write_text("worktree")

    result = run_prec(repo, "run", "--staged")
    assert result.returncode == 0, result.stderr
    assert "passed (exit code: 0)" in result.stdout
    temporary = repo / ".git" / "prec" / "tmp"
    assert not temporary.exists() or list(temporary.iterdir()) == []


def test_staged_uses_indexed_config(repo: Path) -> None:
    indexed = config(
        ['[[checks]]\nid = "which"\nrun = ["true"]\npass_filenames = false\nalways_run = true']
    )
    worktree = indexed.replace('run = ["true"]', 'run = ["false"]')
    (repo / ".prec/prec-config.toml").write_text(indexed)
    (repo / "data.txt").write_text("base")
    commit_all(repo)
    (repo / "data.txt").write_text("staged")
    git(repo, "add", "data.txt")
    (repo / ".prec/prec-config.toml").write_text(worktree)

    result = run_prec(repo, "run", "--staged")
    assert result.returncode == 0, result.stderr
    assert "which" in result.stdout
    assert "passed (exit code: 0)" in result.stdout


def test_staged_runs_indexed_interpreter_script(repo: Path) -> None:
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                '[[checks]]\nid = "script"\nrun = ["python3", "check.py"]\n'
                'files = ["check.py"]\npass_filenames = false'
            ]
        )
    )
    (repo / "check.py").write_text("raise SystemExit(0)  # base\n")
    commit_all(repo)
    (repo / "check.py").write_text("raise SystemExit(0)  # staged\n")
    git(repo, "add", "check.py")
    (repo / "check.py").write_text("raise SystemExit(9)\n")

    result = run_prec(repo, "run", "--staged")
    assert result.returncode == 0, result.stderr
    assert "passed (exit code: 0)" in result.stdout


def test_staged_child_git_uses_disposable_index(repo: Path) -> None:
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                """[[checks]]
id = "mutate-copy"
run = ["sh", "-c", "echo generated > generated.txt; git add generated.txt"]
pass_filenames = false
always_run = true"""
            ]
        )
    )
    (repo / "data.txt").write_text("base")
    commit_all(repo)
    (repo / "data.txt").write_text("staged")
    git(repo, "add", "data.txt")

    before = git(repo, "write-tree").stdout
    result = run_prec(repo, "run", "--staged")
    after = git(repo, "write-tree").stdout
    assert result.returncode == 0, result.stderr
    assert before == after
    assert not (repo / "generated.txt").exists()


def test_staged_snapshot_does_not_include_untracked_files(repo: Path) -> None:
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                """[[checks]]
id = "absence"
run = ["sh", "-c", "test ! -e untracked.txt"]
pass_filenames = false
always_run = true"""
            ]
        )
    )
    (repo / "data.txt").write_text("base")
    commit_all(repo)
    (repo / "data.txt").write_text("staged")
    git(repo, "add", "data.txt")
    (repo / "untracked.txt").write_text("not in index")
    result = run_prec(repo, "run", "--staged")
    assert result.returncode == 0, result.stderr


def test_staged_requires_indexed_regular_config(repo: Path) -> None:
    (repo / ".prec/prec-config.toml").write_text("version = 1\nchecks = []\n")
    absent = run_prec(repo, "run", "--staged")
    assert absent.returncode == 2
    assert "absent from the Git index" in absent.stderr

    (repo / "target.toml").write_text("version = 1\nchecks = []\n")
    (repo / ".prec/prec-config.toml").unlink()
    (repo / ".prec/prec-config.toml").symlink_to("target.toml")
    git(repo, "add", ".prec/prec-config.toml")
    linked = run_prec(repo, "run", "--staged")
    assert linked.returncode == 2
    assert "indexed configuration must not be a symbolic link" in linked.stderr


def test_selected_checks_run_in_config_order(repo: Path) -> None:
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                '[[checks]]\nid = "first"\nrun = ["sh", "-c", "printf FIRST >> order"]\n'
                "pass_filenames = false\nalways_run = true",
                '[[checks]]\nid = "second"\nrun = ["sh", "-c", "printf SECOND >> order"]\n'
                "pass_filenames = false\nalways_run = true",
            ]
        )
    )
    result = run_prec(repo, "run", "second", "first")
    assert result.returncode == 0
    assert (repo / "order").read_text() == "FIRSTSECOND"
    assert result.stdout.index("first") < result.stdout.index("second")


def test_unknown_check_and_mutually_exclusive_sources(repo: Path) -> None:
    (repo / ".prec/prec-config.toml").write_text("version = 1\nchecks = []\n")
    unknown = run_prec(repo, "run", "missing")
    exclusive = run_prec(repo, "run", "--all", "--staged")
    assert unknown.returncode == 2
    assert "unknown check id" in unknown.stderr
    assert exclusive.returncode == 2


def test_failure_error_and_timeout_statuses(repo: Path) -> None:
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                '[[checks]]\nid = "failure"\n'
                'run = ["sh", "-c", "echo diagnostic >&2; exit 1"]\nalways_run = true'
            ]
        )
    )
    failed = run_prec(repo)
    assert failed.returncode == 1
    assert "failure" in failed.stdout
    assert "failed (exit code: 1)" in failed.stdout
    assert "diagnostic" in failed.stderr

    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                '[[checks]]\nid = "missing"\nrun = ["definitely-not-a-prec-command"]\n'
                "always_run = true"
            ]
        )
    )
    missing_command = run_prec(repo)
    assert missing_command.returncode == 2
    assert "error (exit code: N/A)" in missing_command.stdout
    assert "command not found" in missing_command.stderr

    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                """[[checks]]
id = "slow"
run = ["python3", "-c", "import time; time.sleep(10)"]
always_run = true
timeout_seconds = 0.05"""
            ]
        )
    )
    timed = run_prec(repo)
    assert timed.returncode == 2
    assert "timed out" in timed.stderr


def test_missing_config_symlink_and_outside_repository(repo: Path) -> None:
    missing = run_prec(repo)
    assert missing.returncode == 2
    assert "configuration file not found" in missing.stderr

    target = repo / "config-target"
    target.write_text("version = 1\nchecks = []\n")
    (repo / ".prec/prec-config.toml").symlink_to(target)
    linked = run_prec(repo)
    assert linked.returncode == 2
    assert "symbolic link" in linked.stderr

    outside = repo.parent / f"{repo.name}-outside"
    outside.mkdir()
    not_repo = run_prec(outside)
    assert not_repo.returncode == 2
    assert "not inside a Git worktree" in not_repo.stderr


def test_sigterm_stops_active_process_group(repo: Path) -> None:
    child_pid_file = repo / "child.pid"
    code = (
        "import subprocess,time; "
        "p=subprocess.Popen(['sleep','10']); "
        f"open({str(child_pid_file)!r},'w').write(str(p.pid)); "
        "time.sleep(10)"
    )
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                f'[[checks]]\nid = "slow"\nrun = ["python3", "-c", {json.dumps(code)}]\n'
                "always_run = true\npass_filenames = false"
            ]
        )
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "prec"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    for _ in range(100):
        if child_pid_file.exists():
            break
        time.sleep(0.02)
    else:
        process.kill()
        raise AssertionError("check did not start")

    os.kill(process.pid, signal.SIGTERM)
    assert process.wait(timeout=5) == 128 + signal.SIGTERM
    child_pid = int(child_pid_file.read_text())
    for _ in range(50):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        status = Path(f"/proc/{child_pid}/status")
        assert status.exists() and "State:\tZ" in status.read_text()
