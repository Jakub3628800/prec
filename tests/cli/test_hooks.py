import os
from pathlib import Path

from conftest import run_prec


def test_install_and_uninstall_pre_commit_by_default(repo: Path) -> None:
    installed = run_prec(repo, "install")
    hook = repo / ".git/hooks/pre-commit"

    assert installed.returncode == 0, installed.stderr
    assert hook.exists()
    assert os.access(hook, os.X_OK)
    script = hook.read_text()
    assert "# prec-managed-hook" in script
    assert "-m prec run --staged" in script
    assert not (repo / ".git/hooks/pre-push").exists()

    uninstalled = run_prec(repo, "uninstall")
    assert uninstalled.returncode == 0, uninstalled.stderr
    assert not hook.exists()


def test_other_hook_types_are_not_supported(repo: Path) -> None:
    result = run_prec(repo, "install", "--hook-type", "pre-push")

    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
    assert not (repo / ".git/hooks/pre-push").exists()


def test_install_honors_core_hooks_path(repo: Path) -> None:
    custom_hooks = repo / ".githooks"
    result = run_prec(
        repo,
        "install",
        env={
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": str(custom_hooks),
        },
    )

    assert result.returncode == 0, result.stderr
    assert (custom_hooks / "pre-commit").exists()
    assert not (repo / ".git/hooks/pre-commit").exists()


def test_hook_management_does_not_overwrite_custom_hooks(repo: Path) -> None:
    hook = repo / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\necho custom\n")
    hook.chmod(0o755)

    installed = run_prec(repo, "install")
    assert installed.returncode == 2
    assert "not managed by prec" in installed.stderr
    assert hook.read_text() == "#!/bin/sh\necho custom\n"

    uninstalled = run_prec(repo, "uninstall")
    assert uninstalled.returncode == 2
    assert "refusing to remove" in uninstalled.stderr
    assert hook.exists()


def test_install_is_idempotent_and_uninstall_of_absent_hook_succeeds(repo: Path) -> None:
    first = run_prec(repo, "install")
    second = run_prec(repo, "install")
    assert first.returncode == second.returncode == 0

    assert run_prec(repo, "uninstall").returncode == 0
    absent = run_prec(repo, "uninstall")
    assert absent.returncode == 0
    assert "not installed" in absent.stdout
