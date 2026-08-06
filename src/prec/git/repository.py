"""Git repository discovery and subprocess access."""

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from prec.errors.errors import RepositoryError


def _decode_text(value: bytes, description: str) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RepositoryError(f"{description} is not valid UTF-8") from error


def _one_line(value: bytes, description: str) -> str:
    if value.endswith(b"\n"):
        value = value[:-1]
    return _decode_text(value, description)


@dataclass(frozen=True, slots=True)
class Repository:
    root: Path
    git_dir: Path
    index_path: Path
    environment: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def discover(cls, cwd: Path | None = None) -> Self:
        where = cwd or Path.cwd()
        root_raw = cls._discovery_git(where, ["rev-parse", "--show-toplevel"])
        root = Path(_one_line(root_raw, "repository root"))
        git_dir_raw = cls._discovery_git(root, ["rev-parse", "--path-format=absolute", "--git-dir"])
        index_raw = cls._discovery_git(
            root, ["rev-parse", "--path-format=absolute", "--git-path", "index"]
        )
        return cls(
            root=root,
            git_dir=Path(_one_line(git_dir_raw, "Git directory")),
            index_path=Path(_one_line(index_raw, "Git index path")),
        )

    @staticmethod
    def _discovery_git(cwd: Path, arguments: Sequence[str]) -> bytes:
        try:
            result = subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, check=False)
        except FileNotFoundError as error:
            raise RepositoryError("git executable not found on PATH") from error
        except OSError as error:
            raise RepositoryError(f"could not start git: {error}") from error
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()
            if arguments[:2] == ["rev-parse", "--show-toplevel"]:
                raise RepositoryError("not inside a Git worktree")
            raise RepositoryError(f"git {' '.join(arguments)} failed: {detail}")
        return result.stdout

    def git(
        self,
        arguments: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        input_data: bytes | None = None,
    ) -> bytes:
        overrides = dict(self.environment)
        if env is not None:
            overrides.update(env)
        child_env = None
        if overrides:
            child_env = os.environ.copy()
            child_env.update(overrides)
        try:
            result = subprocess.run(
                ["git", *arguments],
                cwd=self.root,
                env=child_env,
                input=input_data,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError as error:
            raise RepositoryError("git executable not found on PATH") from error
        except OSError as error:
            raise RepositoryError(f"could not start git: {error}") from error
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise RepositoryError(f"git {' '.join(arguments)} failed: {detail}")
        return result.stdout

    def has_head(self) -> bool:
        child_env = os.environ.copy()
        child_env.update(self.environment)
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", "HEAD"],
            cwd=self.root,
            env=child_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0
