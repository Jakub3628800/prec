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


def test_all_checks_run_and_error_precedes_failure(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    checks = (
        Check("failure", ("sh", "-c", "exit 7"), always_run=True),
        Check("missing", ("prec-command-that-does-not-exist",), always_run=True),
        Check("later", ("sh", "-c", f"> '{marker}'"), always_run=True),
    )
    results = run_checks(Config(1, checks), (), tmp_path)
    assert [result.state for result in results] == [State.FAILED, State.ERROR, State.PASSED]
    assert marker.exists()
    assert exit_status(results) == 2


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
