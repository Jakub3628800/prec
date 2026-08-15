"""Sequential, bounded check execution."""

import os
import selectors
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from types import FrameType

from prec.config import Config
from prec.errors import TerminationRequested
from prec.runner.plan import PlannedCheck, plan_checks
from prec.runner.result import CheckResult, State

ResultCallback = Callable[[CheckResult], None]
_OUTPUT_LIMIT_BYTES = 1_000_000
_READ_SIZE = 64 * 1024
_SignalHandler = Callable[[int, FrameType | None], object] | int | None


def _stop_process(process: subprocess.Popen[bytes]) -> None:
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


def _capture_chunk(chunk: bytes, output: bytearray, truncated: list[bool]) -> None:
    remaining = _OUTPUT_LIMIT_BYTES - len(output)
    if remaining > 0:
        output.extend(chunk[:remaining])
    if len(chunk) > remaining:
        truncated[0] = True


def _read_ready(
    selector: selectors.BaseSelector,
    events: list[tuple[selectors.SelectorKey, int]],
    *,
    process_active: bool,
) -> None:
    for key, _mask in events:
        output, truncated = key.data
        try:
            chunk = os.read(key.fd, _READ_SIZE)
        except BlockingIOError:
            continue
        if chunk:
            _capture_chunk(chunk, output, truncated)
            if truncated[0] and not process_active:
                selector.unregister(key.fd)
        else:
            selector.unregister(key.fd)


def _append_detail(detail: str | None, addition: str) -> str:
    return f"{detail}; {addition}" if detail else addition


def _run_command(
    check_id: str,
    command: tuple[str, ...],
    root: Path,
    environment: Mapping[str, str],
    timeout_seconds: float | None,
) -> CheckResult:
    child_environment = os.environ.copy()
    child_environment.update(environment)
    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=child_environment,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        return CheckResult(check_id, State.ERROR, detail=f"command not found: {command[0]}")
    except OSError as error:
        return CheckResult(check_id, State.ERROR, detail=f"could not start command: {error}")

    assert process.stdout is not None
    assert process.stderr is not None
    stdout_bytes = bytearray()
    stderr_bytes = bytearray()
    stdout_truncated = [False]
    stderr_truncated = [False]
    streams = (process.stdout, process.stderr)
    selector = selectors.DefaultSelector()
    for stream, output, truncated in (
        (process.stdout, stdout_bytes, stdout_truncated),
        (process.stderr, stderr_bytes, stderr_truncated),
    ):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream.fileno(), selectors.EVENT_READ, (output, truncated))

    previous_handlers: dict[signal.Signals, _SignalHandler] = {}

    def terminate(signum: int, frame: FrameType | None) -> None:
        del frame
        raise TerminationRequested(signum)

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, terminate)

    detail: str | None = None
    state: State
    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    try:
        while process.poll() is None:
            wait_seconds = 0.1
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _stop_process(process)
                    detail = f"timed out after {timeout_seconds:g} seconds"
                    state = State.ERROR
                    break
                wait_seconds = min(wait_seconds, remaining)
            events = selector.select(wait_seconds)
            _read_ready(selector, events, process_active=True)
        else:
            state = State.PASSED if process.returncode == 0 else State.FAILED

        # Drain bytes already available when the process exited, but do not wait
        # for descendants that inherited the pipe descriptors.
        while events := selector.select(0):
            _read_ready(selector, events, process_active=False)
    except BaseException:
        _stop_process(process)
        raise
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        selector.close()
        for stream in streams:
            stream.close()

    if stdout_truncated[0]:
        detail = _append_detail(detail, f"stdout truncated after {_OUTPUT_LIMIT_BYTES} bytes")
    if stderr_truncated[0]:
        detail = _append_detail(detail, f"stderr truncated after {_OUTPUT_LIMIT_BYTES} bytes")
    return CheckResult(
        check_id,
        state,
        returncode=process.returncode,
        detail=detail,
        stdout=stdout_bytes.decode("utf-8", "replace"),
        stderr=stderr_bytes.decode("utf-8", "replace"),
    )


def _merge_results(check_id: str, results: list[CheckResult]) -> CheckResult:
    state = (
        State.ERROR
        if any(result.state is State.ERROR for result in results)
        else State.FAILED
        if any(result.state is State.FAILED for result in results)
        else State.PASSED
    )
    decisive = next((result for result in results if result.state is state), results[0])
    details = list(dict.fromkeys(result.detail for result in results if result.detail))
    stdout = "".join(result.stdout for result in results)
    stderr = "".join(result.stderr for result in results)
    if len(stdout.encode()) > _OUTPUT_LIMIT_BYTES:
        details.append(f"stdout truncated after {_OUTPUT_LIMIT_BYTES} bytes")
    if len(stderr.encode()) > _OUTPUT_LIMIT_BYTES:
        details.append(f"stderr truncated after {_OUTPUT_LIMIT_BYTES} bytes")
    return CheckResult(
        check_id,
        state,
        returncode=decisive.returncode,
        detail="; ".join(dict.fromkeys(details)) or None,
        stdout=stdout.encode()[:_OUTPUT_LIMIT_BYTES].decode("utf-8", "ignore"),
        stderr=stderr.encode()[:_OUTPUT_LIMIT_BYTES].decode("utf-8", "ignore"),
    )


def run_plan(
    plan: tuple[PlannedCheck, ...],
    root: Path,
    environment: Mapping[str, str] | None = None,
    on_result: ResultCallback | None = None,
) -> tuple[CheckResult, ...]:
    """Execute a fully resolved plan in configuration order."""
    environment = environment or {}
    invalid = any(planned.error is not None for planned in plan)
    results: list[CheckResult] = []
    for planned in plan:
        check = planned.check
        if planned.error is not None:
            result = CheckResult(check.id, State.ERROR, detail=planned.error)
        elif invalid:
            result = CheckResult(check.id, State.SKIPPED, detail="not run because plan is invalid")
        elif planned.skipped:
            result = CheckResult(check.id, State.SKIPPED, detail="no matching files")
        else:
            aggregate: CheckResult | None = None
            for command in planned.commands:
                batch = _run_command(check.id, command, root, environment, check.timeout_seconds)
                aggregate = (
                    batch if aggregate is None else _merge_results(check.id, [aggregate, batch])
                )
                if batch.state is State.ERROR:
                    break
            assert aggregate is not None
            result = aggregate
        if on_result is not None:
            on_result(result)
        results.append(result)
    return tuple(results)


def run_checks(
    config: Config,
    candidate_paths: tuple[str, ...],
    root: Path,
    environment: Mapping[str, str] | None = None,
    on_result: ResultCallback | None = None,
) -> tuple[CheckResult, ...]:
    """Plan every check, then run them sequentially."""
    environment = environment or {}
    plan = plan_checks(config, candidate_paths, root, environment)
    return run_plan(plan, root, environment, on_result)
