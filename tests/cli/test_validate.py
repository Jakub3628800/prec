from pathlib import Path

from conftest import run_prec


def test_validate_resolves_all_checks_without_running_them(repo: Path) -> None:
    marker = repo / "ran"
    (repo / ".prec/prec-config.toml").write_text(
        'version = 1\n[[checks]]\nid = "valid"\n'
        f'run = ["sh", "-c", "touch {marker}"]\n'
        "always_run = true\n"
    )
    result = run_prec(repo, "validate")
    assert result.returncode == 0, result.stderr
    assert "valid: valid" in result.stdout
    assert "Configuration valid" in result.stdout
    assert not marker.exists()


def test_validate_reports_missing_executable_even_without_matches(repo: Path) -> None:
    (repo / ".prec/prec-config.toml").write_text(
        'version = 1\n[[checks]]\nid = "missing"\nrun = ["not-a-real-command"]\n'
        'files = ["*.never"]\n'
    )
    result = run_prec(repo, "validate")
    assert result.returncode == 2
    assert "missing: error: command not found" in result.stdout
