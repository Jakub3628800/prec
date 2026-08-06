"""CLI version option."""

import argparse

from prec import __version__


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Add the top-level version option."""
    parser.add_argument("--version", action="version", version=f"prec {__version__}")
