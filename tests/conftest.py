import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    (tmp_path / ".prec").mkdir()
    return tmp_path


def git(
    repo: Path, *arguments: str, input_data: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments], cwd=repo, input=input_data, capture_output=True, check=True
    )


def commit_all(repo: Path, message: str = "initial") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)


def run_prec(
    repo: Path, *arguments: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    child_env = os.environ.copy()
    if env:
        child_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "prec", *arguments],
        cwd=repo,
        env=child_env,
        text=True,
        capture_output=True,
        check=False,
    )


def config(checks: Sequence[str]) -> str:
    return "version = 1\n\n" + "\n\n".join(checks) + "\n"
