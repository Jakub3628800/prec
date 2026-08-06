"""Implementation of the `list` subcommand."""

import argparse

from prec.config.config import load_worktree_config
from prec.git.repository import Repository


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Configure arguments accepted by `prec list`."""


def list_checks(repository: Repository, args: argparse.Namespace) -> int:
    """Print configured check IDs in configuration order."""
    del args
    config = load_worktree_config(repository.root)
    for check in config.checks:
        print(check.id)
    return 0
