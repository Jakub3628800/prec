"""Resolve configuration into an immutable execution plan."""

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from prec.config import Check, Config
from prec.git.patterns import filter_paths


@dataclass(frozen=True, slots=True)
class PlannedCheck:
    """One fully resolved check, including zero or more command invocations."""

    check: Check
    paths: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...] = ()
    error: str | None = None

    @property
    def skipped(self) -> bool:
        return not self.paths and not self.check.always_run


def _resolve_command(
    check: Check, root: Path, environment: Mapping[str, str]
) -> tuple[str, ...] | str:
    if check.script is not None:
        path = root / check.script
        if path.is_symlink():
            return f"custom check script must not be a symbolic link: {check.script}"
        if not path.is_file():
            return f"custom check script not found: {check.script}"
        if not os.access(path, os.X_OK):
            return f"custom check script is not executable: {check.script}"
        return (check.script, "--")

    assert check.run is not None
    executable = check.run[0]
    if "/" in executable:
        path = root / executable
        if not path.is_file():
            return f"command not found: {executable}"
        if not os.access(path, os.X_OK):
            return f"command is not executable: {executable}"
    else:
        child_path = environment.get("PATH", os.environ.get("PATH", os.defpath))
        search_path = os.pathsep.join(
            entry if os.path.isabs(entry) else os.fspath(root / entry)
            for entry in child_path.split(os.pathsep)
        )
        if shutil.which(executable, path=search_path) is None:
            return f"command not found: {executable}"
    return check.run


def _commands(
    check: Check, command: tuple[str, ...], paths: tuple[str, ...]
) -> tuple[tuple[str, ...], ...]:
    if not check.pass_filenames:
        return (command,)
    if check.batch_size is None:
        return ((*command, *paths),)
    return tuple(
        (*command, *paths[start : start + check.batch_size])
        for start in range(0, len(paths), check.batch_size)
    ) or (command,)


def plan_checks(
    config: Config,
    candidate_paths: tuple[str, ...],
    root: Path,
    environment: Mapping[str, str] | None = None,
) -> tuple[PlannedCheck, ...]:
    """Resolve every check before any commands are executed."""
    environment = environment or {}
    planned: list[PlannedCheck] = []
    for check in config.checks:
        paths = filter_paths(candidate_paths, check.files, check.exclude)
        command = _resolve_command(check, root, environment)
        if isinstance(command, str):
            planned.append(PlannedCheck(check, paths, error=command))
            continue
        if not paths and not check.always_run:
            planned.append(PlannedCheck(check, paths))
            continue
        planned.append(PlannedCheck(check, paths, _commands(check, command, paths)))
    return tuple(planned)
