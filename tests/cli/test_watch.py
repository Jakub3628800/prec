import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import commit_all, config, git, run_prec

from prec.errors import RepositoryError
from prec.git.candidates import Source
from prec.git.repository import Repository
from prec.watch import WorktreeState, observe, wait_for_stable_change


def _wait_until(condition: Callable[[], bool], process: subprocess.Popen[str]) -> None:
    for _ in range(100):
        if condition():
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            detail = (
                f"watch process exited with {process.returncode}\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
            raise AssertionError(detail)
        time.sleep(0.05)
    process.kill()
    stdout, stderr = process.communicate()
    detail = f"timed out waiting for watch process\nstdout:\n{stdout}\nstderr:\n{stderr}"
    raise AssertionError(detail)


def test_worktree_observation_tracks_candidates_and_ignores_ignored_files(repo: Path) -> None:
    (repo / ".prec/prec-config.toml").write_text("version = 1\nchecks = []\n")
    (repo / ".gitignore").write_text("ignored.txt\n")
    (repo / "data.txt").write_text("base")
    commit_all(repo)
    repository = Repository.discover(repo)

    baseline = observe(repository, Source.CHANGED)
    (repo / "ignored.txt").write_text("ignored")
    assert observe(repository, Source.CHANGED) == baseline

    (repo / "data.txt").write_text("first change")
    changed = observe(repository, Source.CHANGED)
    assert changed != baseline

    replacement = repo / "replacement"
    replacement.write_text("second value")
    os.replace(replacement, repo / "data.txt")
    assert observe(repository, Source.CHANGED) != changed


def test_worktree_observation_handles_missing_and_unreadable_config(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = Repository.discover(repo)
    state = observe(repository, Source.CHANGED)
    assert isinstance(state, WorktreeState)
    assert state.files == ((".prec/prec-config.toml", None),)

    config_path = repo / ".prec/prec-config.toml"
    config_path.write_text("version = 1\nchecks = []\n")
    commit_all(repo)
    real_lstat = os.lstat

    def denied(path: os.PathLike[str] | str) -> os.stat_result:
        if os.fspath(path) == os.fspath(config_path):
            raise PermissionError("denied for test")
        return real_lstat(path)

    monkeypatch.setattr(os, "lstat", denied)
    with pytest.raises(RepositoryError, match=r"cannot inspect \.prec/prec-config\.toml"):
        observe(repository, Source.CHANGED)


def test_staged_observation_only_changes_with_index_or_head(repo: Path) -> None:
    (repo / ".prec/prec-config.toml").write_text("version = 1\nchecks = []\n")
    (repo / "data.txt").write_text("base")
    commit_all(repo)
    repository = Repository.discover(repo)

    baseline = observe(repository, Source.STAGED)
    (repo / "data.txt").write_text("worktree")
    assert observe(repository, Source.STAGED) == baseline

    git(repo, "add", "data.txt")
    assert observe(repository, Source.STAGED) != baseline


def test_wait_for_stable_change_debounces_observations() -> None:
    baseline = WorktreeState(())
    first = WorktreeState((("first", None),))
    stable = WorktreeState((("stable", None),))
    states = iter((first, stable, stable))
    sleeps: list[float] = []

    result = wait_for_stable_change(
        lambda: next(states),
        baseline,
        on_error=lambda error: None,
        interval_seconds=0.25,
        sleep=sleeps.append,
    )

    assert result == stable
    assert sleeps == [0.25, 0.25, 0.25]


def test_wait_for_stable_change_retries_and_deduplicates_observation_errors() -> None:
    baseline = WorktreeState(())
    changed = WorktreeState((("changed", None),))
    observations: list[WorktreeState | RepositoryError] = [
        RepositoryError("temporarily unavailable"),
        RepositoryError("temporarily unavailable"),
        changed,
        changed,
    ]
    errors: list[str] = []

    def observer() -> WorktreeState:
        observation = observations.pop(0)
        if isinstance(observation, RepositoryError):
            raise observation
        return observation

    result = wait_for_stable_change(
        observer,
        baseline,
        on_error=lambda error: errors.append(str(error)),
        interval_seconds=0,
        sleep=lambda interval: None,
    )

    assert result == changed
    assert errors == ["temporarily unavailable"]


def test_watch_runs_initially_and_after_an_existing_dirty_file_changes(repo: Path) -> None:
    counter = repo.parent / f"{repo.name}-watch-count"
    code = (
        "from pathlib import Path; "
        f"p=Path({str(counter)!r}); "
        "p.write_text(str((int(p.read_text()) if p.exists() else 0) + 1))"
    )
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                f'[[checks]]\nid = "count"\nrun = ["python3", "-c", {json.dumps(code)}]\n'
                'files = ["data.txt"]'
            ]
        )
    )
    (repo / "data.txt").write_text("base")
    commit_all(repo)
    (repo / "data.txt").write_text("first")

    process = subprocess.Popen(
        [sys.executable, "-m", "prec", "run", "--watch"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_until(lambda: counter.exists() and counter.read_text() == "1", process)
        (repo / "data.txt").write_text("second change")
        _wait_until(lambda: counter.exists() and int(counter.read_text()) >= 2, process)
        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()

    assert process.returncode == 128 + signal.SIGTERM
    assert "Watching for changes" in stdout
    assert "Change detected" in stdout
    assert stderr == ""


def test_watch_all_runs_for_clean_tracked_files_and_then_edits(repo: Path) -> None:
    counter = repo.parent / f"{repo.name}-all-count"
    code = (
        "from pathlib import Path; "
        f"p=Path({str(counter)!r}); "
        "p.write_text(str((int(p.read_text()) if p.exists() else 0) + 1))"
    )
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                f'[[checks]]\nid = "count"\nrun = ["python3", "-c", {json.dumps(code)}]\n'
                'files = ["data.txt"]'
            ]
        )
    )
    (repo / "data.txt").write_text("clean")
    commit_all(repo)

    process = subprocess.Popen(
        [sys.executable, "-m", "prec", "run", "--watch", "--all"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_until(lambda: counter.exists() and counter.read_text() == "1", process)
        (repo / "data.txt").write_text("edited")
        _wait_until(lambda: counter.exists() and int(counter.read_text()) >= 2, process)
        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()

    assert process.returncode == 128 + signal.SIGTERM
    assert counter.read_text() == "2"
    assert "passed (exit code: 0)" in stdout
    assert stderr == ""


def test_staged_watch_ignores_worktree_edits_and_runs_exact_index_content(repo: Path) -> None:
    captured = repo.parent / f"{repo.name}-staged-content"
    code = (
        "from pathlib import Path; "
        f"p=Path({str(captured)!r}); "
        "old=p.read_text() if p.exists() else ''; "
        "p.write_text(old + Path('data.txt').read_text() + '\\n')"
    )
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                f'[[checks]]\nid = "capture"\nrun = ["python3", "-c", {json.dumps(code)}]\n'
                'files = ["data.txt"]\npass_filenames = false'
            ]
        )
    )
    (repo / "data.txt").write_text("base")
    commit_all(repo)
    (repo / "data.txt").write_text("staged-one")
    git(repo, "add", "data.txt")

    process = subprocess.Popen(
        [sys.executable, "-m", "prec", "run", "--watch", "--staged"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_until(lambda: captured.exists() and captured.read_text() == "staged-one\n", process)
        (repo / "data.txt").write_text("unstaged-only")
        time.sleep(1.2)
        assert captured.read_text() == "staged-one\n"

        (repo / "data.txt").write_text("staged-two")
        git(repo, "add", "data.txt")
        (repo / "data.txt").write_text("unstaged-after-add")
        _wait_until(lambda: captured.read_text().count("\n") >= 2, process)
        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()

    assert process.returncode == 128 + signal.SIGTERM
    assert captured.read_text() == "staged-one\nstaged-two\n"
    assert "passed (exit code: 0)" in stdout
    assert stderr == ""


def test_watch_recovers_after_configuration_error(repo: Path) -> None:
    counter = repo.parent / f"{repo.name}-recovery-count"
    code = (
        "from pathlib import Path; "
        f"p=Path({str(counter)!r}); "
        "p.write_text(str((int(p.read_text()) if p.exists() else 0) + 1))"
    )
    valid_config = config(
        [
            f'[[checks]]\nid = "count"\nrun = ["python3", "-c", {json.dumps(code)}]\n'
            'files = ["data.txt"]'
        ]
    )
    config_path = repo / ".prec/prec-config.toml"
    config_path.write_text(valid_config)
    (repo / "data.txt").write_text("base")
    commit_all(repo)
    (repo / "data.txt").write_text("dirty")

    process = subprocess.Popen(
        [sys.executable, "-m", "prec", "--watch"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_until(lambda: counter.exists() and counter.read_text() == "1", process)
        config_path.write_text("not valid toml = [")
        time.sleep(1.2)
        assert process.poll() is None
        assert counter.read_text() == "1"

        config_path.write_text(valid_config)
        _wait_until(lambda: int(counter.read_text()) >= 2, process)
        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()

    assert process.returncode == 128 + signal.SIGTERM
    assert counter.read_text() == "2"
    assert "passed (exit code: 0)" in stdout
    assert "invalid TOML" in stderr


def test_watch_continues_after_check_failure(repo: Path) -> None:
    counter = repo.parent / f"{repo.name}-failure-count"
    code = (
        "from pathlib import Path; "
        f"p=Path({str(counter)!r}); "
        "p.write_text(str((int(p.read_text()) if p.exists() else 0) + 1)); "
        "raise SystemExit(7)"
    )
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                f'[[checks]]\nid = "fail"\nrun = ["python3", "-c", {json.dumps(code)}]\n'
                'files = ["data.txt"]'
            ]
        )
    )
    (repo / "data.txt").write_text("base")
    commit_all(repo)
    (repo / "data.txt").write_text("first")

    process = subprocess.Popen(
        [sys.executable, "-m", "prec", "--watch"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_until(lambda: counter.exists() and counter.read_text() == "1", process)
        assert process.poll() is None
        (repo / "data.txt").write_text("second")
        _wait_until(lambda: int(counter.read_text()) >= 2, process)
        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()

    assert process.returncode == 128 + signal.SIGTERM
    assert counter.read_text() == "2"
    assert "failed (exit code: 7)" in stdout
    assert stderr == ""


def test_change_during_running_check_schedules_another_run(repo: Path) -> None:
    counter = repo.parent / f"{repo.name}-during-run-count"
    code = (
        "import time; from pathlib import Path; "
        f"p=Path({str(counter)!r}); "
        "n=(int(p.read_text()) if p.exists() else 0) + 1; "
        "p.write_text(str(n)); "
        "time.sleep(1.2) if n == 1 else None"
    )
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                f'[[checks]]\nid = "slow"\nrun = ["python3", "-c", {json.dumps(code)}]\n'
                'files = ["data.txt"]'
            ]
        )
    )
    (repo / "data.txt").write_text("base")
    commit_all(repo)
    (repo / "data.txt").write_text("first")

    process = subprocess.Popen(
        [sys.executable, "-m", "prec", "--watch"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_until(lambda: counter.exists() and counter.read_text() == "1", process)
        (repo / "data.txt").write_text("changed while running")
        _wait_until(lambda: int(counter.read_text()) >= 2, process)
        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()

    assert process.returncode == 128 + signal.SIGTERM
    assert counter.read_text() == "2"
    assert "passed (exit code: 0)" in stdout
    assert stderr == ""


def test_signal_during_watched_check_terminates_process_group(repo: Path) -> None:
    child_pid_file = repo.parent / f"{repo.name}-watch-child-pid"
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
    commit_all(repo)

    process = subprocess.Popen(
        [sys.executable, "-m", "prec", "--watch"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_until(child_pid_file.exists, process)
        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()

    assert process.returncode == 128 + signal.SIGTERM
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
    assert "Watching for changes" in stdout
    assert stderr == ""


def test_sigint_stops_watch(repo: Path) -> None:
    ready = repo.parent / f"{repo.name}-sigint-ready"
    code = f"from pathlib import Path; Path({str(ready)!r}).touch()"
    (repo / ".prec/prec-config.toml").write_text(
        config(
            [
                f'[[checks]]\nid = "ready"\nrun = ["python3", "-c", {json.dumps(code)}]\n'
                "always_run = true\npass_filenames = false"
            ]
        )
    )
    commit_all(repo)
    process = subprocess.Popen(
        [sys.executable, "-m", "prec", "--watch"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_until(ready.exists, process)
        time.sleep(0.2)
        os.kill(process.pid, signal.SIGINT)
        stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()

    assert process.returncode == 128 + signal.SIGINT
    assert "Watching for changes" in stdout
    assert stderr == ""


def test_watch_initial_configuration_and_selection_errors_are_fatal(repo: Path) -> None:
    config_path = repo / ".prec/prec-config.toml"
    config_path.write_text("invalid = [")
    invalid = run_prec(repo, "--watch")
    assert invalid.returncode == 2
    assert "invalid TOML" in invalid.stderr

    config_path.write_text("version = 1\nchecks = []\n")
    unknown = run_prec(repo, "--watch", "missing")
    assert unknown.returncode == 2
    assert "unknown check id" in unknown.stderr
