"""Implementation of the `validate` subcommand."""

import argparse

from prec.config.config import load_worktree_config
from prec.git.candidates import Source, candidates
from prec.git.repository import Repository
from prec.runner.plan import plan_checks


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Configure arguments accepted by `prec validate`."""


def validate(repository: Repository, args: argparse.Namespace) -> int:
    """Validate configuration and resolve every configured executable."""
    del args
    config = load_worktree_config(repository.root)
    paths = candidates(repository, Source.ALL)
    plan = plan_checks(config, paths, repository.root)
    errors = 0
    for planned in plan:
        if planned.error is not None:
            print(f"{planned.check.id}: error: {planned.error}")
            errors += 1
        else:
            suffix = "path" if len(planned.paths) == 1 else "paths"
            print(f"{planned.check.id}: valid ({len(planned.paths)} matching {suffix})")
    if errors:
        print(f"Configuration invalid: {errors} unresolved check(s)")
        return 2
    print(f"Configuration valid: {len(plan)} check(s)")
    return 0
