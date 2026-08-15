import json
import os
import time
from pathlib import Path

from prec.config.config import Check, Config
from prec.runner.result import State, exit_status
from prec.runner.runner import run_checks


def test_filenames_are_individual_arguments_in_sorted_input_order(tmp_path: Path) -> None:
    output = tmp_path / "argv.json"
    code = "import json,sys; open(sys.argv[1], 'w').write(json.dumps(sys.argv[2:]))"
    check = Check("capture", ("python3", "-c", code, str(output)), files=("*.py",))
    results = run_checks(Config(1, (check,)), ("a.py", "dir/b.py", "x.txt"), tmp_path)
    assert results[0].state is State.PASSED
    assert json.loads(output.read_text()) == ["a.py", "dir/b.py"]


def test_relative_path_entries_are_resolved_from_execution_root(tmp_path: Path) -> None:
    executable = tmp_path / "bin" / "local-check"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    nested = tmp_path / "nested"
    nested.mkdir()
    previous_cwd = Path.cwd()
    try:
        os.chdir(nested)
        check = Check("local", ("local-check",), always_run=True, pass_filenames=False)
        result = run_checks(Config(1, (check,)), (), tmp_path, {"PATH": "bin"})[0]
    finally:
        os.chdir(previous_cwd)
    assert result.state is State.PASSED


def test_pass_filenames_false(tmp_path: Path) -> None:
    output = tmp_path / "argv.json"
    code = "import json,sys; open(sys.argv[1], 'w').write(json.dumps(sys.argv[2:]))"
    check = Check(
        "capture", ("python3", "-c", code, str(output)), pass_filenames=False, always_run=True
    )
    run_checks(Config(1, (check,)), ("a.py",), tmp_path)
    assert json.loads(output.read_text()) == []


def test_skip_and_always_run(tmp_path: Path) -> None:
    skipped = Check("skip", ("true",))
    always = Check("always", ("true",), always_run=True, pass_filenames=False)
    results = run_checks(Config(1, (skipped, always)), (), tmp_path)
    assert [result.state for result in results] == [State.SKIPPED, State.PASSED]


def test_invalid_plan_prevents_any_commands_from_running(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    checks = (
        Check("failure", ("sh", "-c", "exit 7"), always_run=True),
        Check("missing", ("prec-command-that-does-not-exist",), always_run=True),
        Check("later", ("sh", "-c", f"> '{marker}'"), always_run=True),
    )
    results = run_checks(Config(1, checks), (), tmp_path)
    assert [result.state for result in results] == [State.SKIPPED, State.ERROR, State.SKIPPED]
    assert not marker.exists()
    assert exit_status(results) == 2


def test_filename_batches_are_aggregated(tmp_path: Path) -> None:
    output = tmp_path / "batches"
    code = "import sys; open(sys.argv[1], 'a').write('|'.join(sys.argv[2:]) + '\\n')"
    check = Check("capture", ("python3", "-c", code, str(output)), files=("*.py",), batch_size=2)
    results = run_checks(Config(1, (check,)), ("a.py", "b.py", "c.py"), tmp_path)
    assert results[0].state is State.PASSED
    assert output.read_text().splitlines() == ["a.py|b.py", "c.py"]


def test_output_is_bounded(tmp_path: Path) -> None:
    code = "import sys; sys.stderr.write('x' * 1100000); raise SystemExit(1)"
    check = Check("verbose", ("python3", "-c", code), always_run=True)
    result = run_checks(Config(1, (check,)), (), tmp_path)[0]
    assert result.state is State.FAILED
    assert len(result.stderr.encode()) == 1_000_000
    assert "stderr truncated" in (result.detail or "")


def test_exited_check_does_not_wait_for_descendant_holding_output_pipe(tmp_path: Path) -> None:
    pid_file = tmp_path / "descendant.pid"
    code = (
        "import subprocess; "
        "p=subprocess.Popen(['sleep','2']); "
        f"open({str(pid_file)!r},'w').write(str(p.pid))"
    )
    check = Check("background", ("python3", "-c", code), always_run=True)
    started = time.monotonic()
    result = run_checks(Config(1, (check,)), (), tmp_path)[0]
    elapsed = time.monotonic() - started
    assert result.state is State.PASSED
    assert elapsed < 1.0


def test_timeout_is_error(tmp_path: Path) -> None:
    check = Check(
        "slow",
        ("python3", "-c", "import time; time.sleep(10)"),
        always_run=True,
        timeout_seconds=0.05,
    )
    results = run_checks(Config(1, (check,)), (), tmp_path)
    assert results[0].state is State.ERROR
    assert "timed out" in (results[0].detail or "")
    assert exit_status(results) == 2


def test_timeout_terminates_descendant_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    code = (
        "import subprocess,time; "
        "p=subprocess.Popen(['sleep','10']); "
        f"open({str(pid_file)!r},'w').write(str(p.pid)); "
        "time.sleep(10)"
    )
    check = Check("tree", ("python3", "-c", code), always_run=True, timeout_seconds=0.2)
    results = run_checks(Config(1, (check,)), (), tmp_path)
    assert results[0].state is State.ERROR
    child_pid = int(pid_file.read_text())
    for _ in range(50):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        # A killed process may briefly remain a zombie; Linux exposes that state.
        status = Path(f"/proc/{child_pid}/status")
        assert status.exists() and "State:\tZ" in status.read_text()
