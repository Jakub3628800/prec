"""Git-wildmatch pattern validation and matching."""

from dataclasses import dataclass
from typing import Self

import pathspec
from pathspec.patterns.gitwildmatch import GitWildMatchPatternError


class PatternError(ValueError):
    """A pattern is outside prec's supported Git-wildmatch subset."""


def validate_pattern(pattern: str) -> None:
    if not pattern:
        raise PatternError("pattern must not be empty")
    if "\0" in pattern:
        raise PatternError("pattern must not contain NUL")
    path = pattern[1:] if pattern.startswith("/") else pattern
    if ".." in path.rstrip("/").split("/"):
        raise PatternError("pattern must not contain a `..` path component")
    if pattern.startswith("!"):
        raise PatternError("pattern negation is not supported; use `exclude`")
    try:
        pathspec.PathSpec.from_lines("gitwildmatch", [_adapt_pattern(pattern)])
    except (GitWildMatchPatternError, ValueError) as error:
        raise PatternError(f"invalid Git-wildmatch pattern `{pattern}`: {error}") from error


def _adapt_pattern(pattern: str) -> str:
    # In config, patterns are values rather than lines in a .gitignore file.
    # Preserve a leading # as a literal rather than a comment marker.
    if pattern.startswith("#"):
        pattern = "\\" + pattern
    # Our spec treats the slash in a root directory pattern as anchoring it.
    # Gitignore itself treats `vendor/` as matching that directory at any depth.
    if pattern.endswith("/") and pattern.count("/") == 1:
        pattern = "/" + pattern
    return pattern


@dataclass(frozen=True, slots=True)
class PatternSet:
    """A set in which any matching pattern yields true."""

    spec: pathspec.PathSpec

    @classmethod
    def compile(cls, patterns: tuple[str, ...]) -> Self:
        return cls(pathspec.PathSpec.from_lines("gitwildmatch", map(_adapt_pattern, patterns)))

    def matches(self, path: str) -> bool:
        return self.spec.match_file(path)


def filter_paths(
    paths: tuple[str, ...], files: tuple[str, ...] | None, exclude: tuple[str, ...]
) -> tuple[str, ...]:
    includes = PatternSet.compile(files) if files is not None else None
    excludes = PatternSet.compile(exclude) if exclude else None
    return tuple(
        path
        for path in paths
        if (includes is None or includes.matches(path))
        and (excludes is None or not excludes.matches(path))
    )
