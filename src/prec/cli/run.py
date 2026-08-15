"""Implementation of the `run` subcommand."""

import argparse
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from prec.config import Config, load_index_config, load_worktree_config
from prec.errors import UsageError
from prec.git.candidates import Source, candidates
from prec.git.repository import Repository
from prec.git.snapshot import index_snapshot
from prec.runner.output import print_result, print_summary
from prec.runner.result import exit_status
from prec.runner.runner import run_checks


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Configure arguments accepted by `prec run`."""
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--staged", action="store_true", help="use exact Git index contents")
    source.add_argument("--all", action="store_true", help="use all tracked and unignored files")
    parser.add_argument("check_ids", nargs="*", metavar="CHECK_ID")


def _select_checks(config: Config, requested: list[str]) -> Config:
    if not requested:
        return config
    known = {check.id for check in config.checks}
    unknown = sorted(set(requested) - known)
    if unknown:
        formatted = ", ".join(f"`{item}`" for item in unknown)
        raise UsageError(f"unknown check id: {formatted}")
    requested_set = set(requested)
    return replace(config, checks=tuple(c for c in config.checks if c.id in requested_set))


def _execute(
    config: Config,
    paths: tuple[str, ...],
    root: Path,
    environment: Mapping[str, str],
) -> int:
    results = run_checks(config, paths, root, environment, on_result=print_result)
    print_summary(results)
    return exit_status(results)


def run(repository: Repository, args: argparse.Namespace) -> int:
    """Run selected checks and return the process status."""
    source = Source.STAGED if args.staged else Source.ALL if args.all else Source.CHANGED
    if source is Source.STAGED:
        # Copy the index first so config, candidate selection, and execution all
        # observe one immutable index generation.
        with index_snapshot(repository) as snapshot:
            config = _select_checks(load_index_config(snapshot.repository), args.check_ids)
            paths = candidates(snapshot.repository, source)
            return _execute(config, paths, snapshot.root, snapshot.environment)
    config = _select_checks(load_worktree_config(repository.root), args.check_ids)
    paths = candidates(repository, source)
    return _execute(config, paths, repository.root, {})
