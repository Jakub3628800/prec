"""Human-readable check result rendering."""

import os
import sys
from typing import TextIO

from prec.runner.result import CheckResult, State

_GREEN = "\033[32m"
_RED = "\033[31m"
_RESET = "\033[0m"
_LINE_WIDTH = 72


def _display_status(result: CheckResult) -> str:
    if result.state is State.PASSED:
        return "passed"
    if result.state is State.FAILED:
        return "failed"
    if result.state is State.SKIPPED:
        return "skipped"
    return "error"


def _styled_status(status: str) -> str:
    if not sys.stdout.isatty() or "NO_COLOR" in os.environ:
        return status
    if status == "passed":
        return f"{_GREEN}{status}{_RESET}"
    if status in {"failed", "error"}:
        return f"{_RED}{status}{_RESET}"
    return status


def _write_output(label: str, content: str, stream: TextIO) -> None:
    if not content:
        return
    print(f"  {label}:", file=stream)
    stream.write(content)
    if not content.endswith("\n"):
        stream.write("\n")
    stream.flush()


def print_result(result: CheckResult) -> None:
    """Print one result line and any failure output."""
    status = _display_status(result)
    if result.state is State.SKIPPED:
        plain_suffix = status
        suffix = _styled_status(status)
    else:
        code = str(result.returncode) if result.returncode is not None else "N/A"
        plain_suffix = f"{status} (exit code: {code})"
        suffix = f"{_styled_status(status)} (exit code: {code})"
    dots = "." * max(1, _LINE_WIDTH - len(result.check_id) - len(plain_suffix))
    print(f"{result.check_id}{dots}{suffix}", flush=True)

    if result.state in {State.PASSED, State.SKIPPED}:
        return
    if result.detail:
        print(f"  {result.detail}", file=sys.stderr, flush=True)
    _write_output("stdout", result.stdout, sys.stdout)
    _write_output("stderr", result.stderr, sys.stderr)


def print_summary(results: tuple[CheckResult, ...]) -> None:
    """Print display-status totals for a completed run."""
    passed = sum(_display_status(result) == "passed" for result in results)
    failed = sum(_display_status(result) == "failed" for result in results)
    error = sum(_display_status(result) == "error" for result in results)
    skipped = sum(_display_status(result) == "skipped" for result in results)
    print(
        f"Summary: {passed} {_styled_status('passed')}, "
        f"{failed} {_styled_status('failed')}, "
        f"{error} {_styled_status('error')}, {skipped} skipped"
    )
