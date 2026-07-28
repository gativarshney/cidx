"""Command-line entry point for cidx.

Thin dispatcher only: subcommands arrive in later phases and must delegate to
library code shared with the MCP server (see ARCHITECTURE.md).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from importlib.metadata import version


def build_parser() -> argparse.ArgumentParser:
    """Return the top-level argument parser for the ``cidx`` command."""
    parser = argparse.ArgumentParser(
        prog="cidx",
        description="Zero-config local code index for AI coding agents.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('cidx')}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit status."""
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
