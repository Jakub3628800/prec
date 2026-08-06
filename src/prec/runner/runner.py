"""Sequential check execution."""

import os
import signal
import subprocess
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path

from prec.config.config import Check, Config
from prec.git.patterns import filter_paths
from prec.runner.result import CheckResult, State

ResultCallback = Callable[[CheckResult], None]


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def _run_one(
    check: Check,
    paths: tuple[str, ...],
    root: Path,
    environment: Mapping[str, str],
) -> CheckResult:
    argv = [*check.run]
    if check.pass_filenames:
        argv.extend(paths)

    child_environment = os.environ.copy()
    child_environment.update(environment)
    try:
        process = subprocess.Popen(
            argv,
            cwd=root,
            env=child_environment,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return CheckResult(
            check.id,
            State.ERROR,
            detail=f"command not found: {check.run[0]}",
        )
    except OSError as error:
        return CheckResult(
            check.id,
            State.ERROR,
            detail=f"could not start command: {error}",
        )

    try:
        stdout, stderr = process.communicate(timeout=check.timeout_seconds)
    except subprocess.TimeoutExpired:
        _stop_process(process)
        stdout, stderr = process.communicate()
        return CheckResult(
            check.id,
            State.ERROR,
            returncode=process.returncode,
            detail=f"timed out after {check.timeout_seconds:g} seconds",
            stdout=stdout,
            stderr=stderr,
        )
    except KeyboardInterrupt:
        _stop_process(process)
        process.communicate()
        raise

    state = State.PASSED if process.returncode == 0 else State.FAILED
    return CheckResult(
        check.id,
        state,
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def run_checks(
    config: Config,
    candidate_paths: tuple[str, ...],
    root: Path,
    environment: Mapping[str, str] | None = None,
    on_result: ResultCallback | None = None,
) -> tuple[CheckResult, ...]:
    """Run all checks, optionally reporting each result as it completes."""
    environment = environment or {}
    results: list[CheckResult] = []
    for check in config.checks:
        paths = filter_paths(candidate_paths, check.files, check.exclude)
        if not paths and not check.always_run:
            result = CheckResult(check.id, State.SKIPPED, detail="no matching files")
        else:
            result = _run_one(check, paths, root, environment)
        if on_result is not None:
            on_result(result)
        results.append(result)
    return tuple(results)
