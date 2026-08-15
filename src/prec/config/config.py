"""Load and validate the version 1 TOML configuration."""

import difflib
import math
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from prec.errors.errors import ConfigError
from prec.git.patterns import PatternError, validate_pattern

CONFIG_PATH = ".prec/prec-config.toml"
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_TOP_FIELDS = frozenset({"version", "checks"})
_CHECK_FIELDS = frozenset(
    {
        "id",
        "run",
        "script",
        "files",
        "exclude",
        "pass_filenames",
        "always_run",
        "timeout_seconds",
        "batch_size",
    }
)


@dataclass(frozen=True, slots=True)
class Check:
    id: str
    run: tuple[str, ...] | None = None
    script: str | None = None
    files: tuple[str, ...] | None = None
    exclude: tuple[str, ...] = ()
    pass_filenames: bool = True
    always_run: bool = False
    timeout_seconds: float | None = None
    batch_size: int | None = None


@dataclass(frozen=True, slots=True)
class Config:
    version: int
    checks: tuple[Check, ...]


def valid_check_id(value: str) -> bool:
    """Return whether a value is a valid check identifier."""
    return len(value) <= 64 and _ID_RE.fullmatch(value) is not None


def _repository_relative_path(value: Any, source: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{source}: expected a non-empty repository-relative path")
    path = PurePosixPath(value)
    if (
        "\0" in value
        or not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or value.endswith("/")
    ):
        raise ConfigError(f"{source}: expected a repository-relative file path")
    return value


def _location(source: str, key: str | None = None) -> str:
    if key is None:
        return source
    separator = ": " if source.endswith(".toml") else "."
    return f"{source}{separator}{key}"


def _unknown_fields(data: dict[str, Any], allowed: frozenset[str], source: str) -> None:
    for field in data:
        if field not in allowed:
            match = difflib.get_close_matches(field, allowed, n=1)
            hint = f"; did you mean `{match[0]}`?" if match else ""
            raise ConfigError(f"{_location(source, field)}: unknown field{hint}")


def _required(data: dict[str, Any], field: str, source: str) -> Any:
    if field not in data:
        raise ConfigError(f"{_location(source, field)}: required field is missing")
    return data[field]


def _string_array(
    value: Any,
    *,
    source: str,
    field: str,
    allow_empty: bool,
    allow_empty_strings: bool = False,
) -> tuple[str, ...]:
    key = _location(source, field)
    if not isinstance(value, list):
        raise ConfigError(f"{key}: expected an array of strings")
    if not value and not allow_empty:
        raise ConfigError(f"{key}: array must not be empty")
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ConfigError(f"{key}[{index}]: expected a string")
        if not item and not allow_empty_strings:
            raise ConfigError(f"{key}[{index}]: string must not be empty")
    return tuple(value)


def _boolean(data: dict[str, Any], field: str, default: bool, source: str) -> bool:
    value = data.get(field, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{_location(source, field)}: expected a boolean")
    return value


def _validate_patterns(patterns: tuple[str, ...], source: str) -> None:
    for pattern in patterns:
        try:
            validate_pattern(pattern)
        except PatternError as error:
            raise ConfigError(f"{source}: {error}") from error


def _parse_check(raw: Any, index: int) -> Check:
    source = f"checks[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: expected a table")
    if not all(isinstance(key, str) for key in raw):  # tomllib guarantees this
        raise ConfigError(f"{source}: table keys must be strings")
    _unknown_fields(raw, _CHECK_FIELDS, source)

    check_id = _required(raw, "id", source)
    if not isinstance(check_id, str):
        raise ConfigError(f"{_location(source, 'id')}: expected a string")
    if not valid_check_id(check_id):
        raise ConfigError(
            f"{_location(source, 'id')}: must match ^[a-z][a-z0-9_-]*$ and be at most 64 characters"
        )

    run: tuple[str, ...] | None = None
    if "run" in raw:
        run = _string_array(
            raw["run"],
            source=source,
            field="run",
            allow_empty=False,
            allow_empty_strings=True,
        )
        if not run[0]:
            raise ConfigError(f"{_location(source, 'run')}[0]: executable must not be empty")
        if "/" in run[0]:
            executable = PurePosixPath(run[0])
            if executable.is_absolute() or ".." in executable.parts:
                location = _location(source, "run")
                raise ConfigError(
                    f"{location}[0]: executable path must be relative to the repository"
                )

    script: str | None = None
    if "script" in raw:
        script = _repository_relative_path(raw["script"], _location(source, "script"))
    if (run is None) == (script is None):
        raise ConfigError(f"{source}: exactly one of `run` or `script` is required")

    files: tuple[str, ...] | None = None
    if "files" in raw:
        files = _string_array(raw["files"], source=source, field="files", allow_empty=False)
        _validate_patterns(files, _location(source, "files"))

    exclude = _string_array(
        raw.get("exclude", []), source=source, field="exclude", allow_empty=True
    )
    _validate_patterns(exclude, _location(source, "exclude"))

    timeout: float | None = None
    if "timeout_seconds" in raw:
        value = raw["timeout_seconds"]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ConfigError(
                f"{_location(source, 'timeout_seconds')}: expected a positive finite number"
            )
        if not math.isfinite(value) or value <= 0:
            raise ConfigError(
                f"{_location(source, 'timeout_seconds')}: expected a positive finite number"
            )
        timeout = float(value)

    batch_size: int | None = None
    if "batch_size" in raw:
        value = raw["batch_size"]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigError(f"{_location(source, 'batch_size')}: expected a positive integer")
        batch_size = value

    return Check(
        id=check_id,
        run=run,
        script=script,
        files=files,
        exclude=exclude,
        pass_filenames=_boolean(raw, "pass_filenames", True, source),
        always_run=_boolean(raw, "always_run", False, source),
        timeout_seconds=timeout,
        batch_size=batch_size,
    )


def loads_config(content: bytes, source: str = CONFIG_PATH) -> Config:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigError(f"{source}: configuration must be valid UTF-8") from error
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{source}: invalid TOML: {error}") from error

    _unknown_fields(raw, _TOP_FIELDS, source)
    version = _required(raw, "version", source)
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise ConfigError(f"{_location(source, 'version')}: expected integer 1")

    raw_checks = _required(raw, "checks", source)
    if not isinstance(raw_checks, list):
        raise ConfigError(f"{_location(source, 'checks')}: expected an array of tables")
    checks = tuple(_parse_check(raw_check, index) for index, raw_check in enumerate(raw_checks))

    seen: set[str] = set()
    for check in checks:
        if check.id in seen:
            raise ConfigError(f"{_location(source, 'checks')}: duplicate check id `{check.id}`")
        seen.add(check.id)
    return Config(version=version, checks=checks)


def load_worktree_config(root: Path) -> Config:
    path = root / CONFIG_PATH
    if path.is_symlink():
        raise ConfigError(f"{CONFIG_PATH}: configuration must not be a symbolic link")
    try:
        content = path.read_bytes()
    except FileNotFoundError as error:
        raise ConfigError(f"{CONFIG_PATH}: configuration file not found") from error
    except OSError as error:
        raise ConfigError(f"{CONFIG_PATH}: cannot read configuration: {error}") from error
    return loads_config(content)
