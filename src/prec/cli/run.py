"""Implementation of the `run` subcommand."""

import argparse
import signal
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import FrameType

from prec.config import Config, load_index_config, load_worktree_config
from prec.errors import PrecError, TerminationRequested, UsageError
from prec.git.candidates import Source, candidates
from prec.git.repository import Repository
from prec.git.snapshot import index_snapshot
from prec.runner.output import print_result, print_summary
from prec.runner.result import exit_status
from prec.runner.runner import run_checks
from prec.watch import observe, wait_for_stable_change

_SignalHandler = Callable[[int, FrameType | None], object] | int | None


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Configure arguments accepted by `prec run`."""
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--staged", action="store_true", help="use exact Git index contents")
    source.add_argument("--all", action="store_true", help="use all tracked and unignored files")
    parser.add_argument("--watch", action="store_true", help="rerun checks when files change")
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


def _run_once(repository: Repository, source: Source, check_ids: list[str]) -> int:
    if source is Source.STAGED:
        # Copy the index first so config, candidate selection, and execution all
        # observe one immutable index generation.
        with index_snapshot(repository) as snapshot:
            config = _select_checks(load_index_config(snapshot.repository), check_ids)
            paths = candidates(snapshot.repository, source)
            return _execute(config, paths, snapshot.root, snapshot.environment)
    config = _select_checks(load_worktree_config(repository.root), check_ids)
    paths = candidates(repository, source)
    return _execute(config, paths, repository.root, {})


@contextmanager
def _watch_signals() -> Iterator[None]:
    previous_handlers: dict[signal.Signals, _SignalHandler] = {}

    def terminate(signum: int, frame: FrameType | None) -> None:
        del frame
        raise TerminationRequested(signum)

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, terminate)
        yield
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def _print_watch_error(error: PrecError) -> None:
    print(f"prec: error: {error}", file=sys.stderr, flush=True)


def _watch(repository: Repository, source: Source, check_ids: list[str]) -> int:
    baseline = observe(repository, source)
    print("Watching for changes. Press Ctrl-C to stop.", flush=True)
    with _watch_signals():
        # Initial configuration and usage errors remain fatal. Once watching has
        # started, transient errors are reported and retried after another change.
        _run_once(repository, source, check_ids)
        while True:
            baseline = wait_for_stable_change(
                lambda: observe(repository, source), baseline, on_error=_print_watch_error
            )
            print("\nChange detected; running checks again.", flush=True)
            try:
                _run_once(repository, source, check_ids)
            except PrecError as error:
                _print_watch_error(error)


def run(repository: Repository, args: argparse.Namespace) -> int:
    """Run selected checks and return the process status."""
    source = Source.STAGED if args.staged else Source.ALL if args.all else Source.CHANGED
    if args.watch:
        return _watch(repository, source, args.check_ids)
    return _run_once(repository, source, args.check_ids)
