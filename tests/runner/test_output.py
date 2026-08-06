import io
import sys

import pytest

from prec.runner.output import print_result, print_summary
from prec.runner.result import CheckResult, State


def test_human_output_has_status_codes_and_failure_streams(
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = (
        CheckResult(
            "success", State.PASSED, 0, stdout="hidden-success\n", stderr="hidden-warning\n"
        ),
        CheckResult(
            "failure", State.FAILED, 1, stdout="failure-output\n", stderr="failure-error\n"
        ),
        CheckResult("unusual", State.FAILED, 7),
        CheckResult("missing", State.ERROR, detail="command not found"),
        CheckResult("skipped", State.SKIPPED),
    )
    for result in results:
        print_result(result)
    print_summary(results)
    captured = capsys.readouterr()

    assert "success (exit code: 0)" in captured.out
    assert "error (exit code: 1)" in captured.out
    assert "other (exit code: 7)" in captured.out
    assert "other (exit code: N/A)" in captured.out
    assert "skipped" in captured.out
    assert "Summary: 1 success, 1 error, 2 other, 1 skipped" in captured.out
    assert "hidden-success" not in captured.out
    assert "hidden-warning" not in captured.err
    assert "failure-output" in captured.out
    assert "failure-error" in captured.err
    assert "command not found" in captured.err
    assert "\033[" not in captured.out


def test_terminal_colors_success_green_and_error_red(monkeypatch: pytest.MonkeyPatch) -> None:
    class TerminalBuffer(io.StringIO):
        def isatty(self) -> bool:
            return True

    output = TerminalBuffer()
    monkeypatch.setattr(sys, "stdout", output)
    print_result(CheckResult("good", State.PASSED, 0))
    print_result(CheckResult("bad", State.FAILED, 1))
    rendered = output.getvalue()
    assert "\033[32msuccess\033[0m (exit code: 0)" in rendered
    assert "\033[31merror\033[0m (exit code: 1)" in rendered
