"""Check result models and process exit status."""

from dataclasses import dataclass
from enum import Enum


class State(Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class CheckResult:
    check_id: str
    state: State
    returncode: int | None = None
    detail: str | None = None
    stdout: str = ""
    stderr: str = ""


def exit_status(results: tuple[CheckResult, ...]) -> int:
    """Return the overall CLI status for completed checks."""
    if any(result.state is State.ERROR for result in results):
        return 2
    if any(result.state is State.FAILED for result in results):
        return 1
    return 0
