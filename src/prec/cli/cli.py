"""Top-level command-line parsing and dispatch."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from prec.cli.hooks import configure_parser as configure_hook_parser
from prec.cli.hooks import install, uninstall
from prec.cli.list import configure_parser as configure_list_parser
from prec.cli.list import list_checks
from prec.cli.run import configure_parser as configure_run_parser
from prec.cli.run import run
from prec.cli.version import configure_parser as configure_version_parser
from prec.errors.errors import PrecError
from prec.git.repository import Repository


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prec", description="Run local checks against Git files.")
    configure_version_parser(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run configured checks")
    configure_run_parser(run_parser)

    list_parser = subparsers.add_parser("list", help="list configured checks")
    configure_list_parser(list_parser)

    install_parser = subparsers.add_parser("install", help="install a Git hook")
    configure_hook_parser(install_parser)

    uninstall_parser = subparsers.add_parser("uninstall", help="uninstall a Git hook")
    configure_hook_parser(uninstall_parser)
    return parser


def _normalize_argv(arguments: Sequence[str]) -> list[str]:
    argv = list(arguments)
    if not argv:
        return ["run"]
    if argv[0] in {"run", "list", "install", "uninstall", "-h", "--help", "--version"}:
        return argv
    if argv[0].startswith("-"):
        return ["run", *argv]
    return argv


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    arguments = _normalize_argv(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    args = parser.parse_args(arguments)
    try:
        repository = Repository.discover(Path.cwd())
        if args.command == "run":
            return run(repository, args)
        if args.command == "list":
            return list_checks(repository, args)
        if args.command == "install":
            return install(repository, args)
        if args.command == "uninstall":
            return uninstall(repository, args)
        parser.error(f"unknown command: {args.command}")
    except KeyboardInterrupt:
        return 130
    except PrecError as error:
        print(f"prec: error: {error}", file=sys.stderr)
        return 2
    return 2
