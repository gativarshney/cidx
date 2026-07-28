"""Command-line entry point for cidx.

Thin dispatcher only: every subcommand delegates to the same library code the
MCP server will call (see ARCHITECTURE.md), so the two consumers cannot
drift. Later phases add ``serve`` and ``check``.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

from cidx.core import indexer, repoid
from cidx.core.store import Store, SymbolRow


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
    subparsers = parser.add_subparsers(dest="command")

    index = subparsers.add_parser(
        "index", help="build or refresh the index for a repository"
    )
    _add_common_arguments(index)

    query = subparsers.add_parser(
        "query", help="look up symbols by exact name, then fuzzy match"
    )
    query.add_argument("name", help="symbol name, qualified name, or prefix")
    query.add_argument(
        "--limit", type=int, default=20, help="maximum results (default 20)"
    )
    _add_common_arguments(query)

    stats = subparsers.add_parser("stats", help="show index size and location")
    _add_common_arguments(stats)

    return parser


def _add_common_arguments(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "--repo",
        default=".",
        help="repository root (default: current directory)",
    )
    subparser.add_argument(
        "--json", action="store_true", help="machine-readable output"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit status."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "index":
        return _run_index(args)
    if args.command == "query":
        return _run_query(args)
    return _run_stats(args)


def _run_index(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    if not repo_root.is_dir():
        print(f"error: {repo_root} is not a directory", file=sys.stderr)
        return 1
    db_path = repoid.index_path(repo_root)
    started = time.perf_counter()
    with Store.open(db_path) as store:
        result = indexer.index_repository(repo_root, store)
        counts = store.stats()
    elapsed = time.perf_counter() - started
    if args.json:
        print(
            json.dumps(
                {
                    "indexed": result.indexed,
                    "skipped_large": result.skipped_large,
                    "failed": result.failed,
                    "symbols": counts["symbols"],
                    "refs": counts["refs"],
                    "seconds": round(elapsed, 3),
                    "db": str(db_path),
                }
            )
        )
    else:
        print(
            f"indexed {result.indexed} files"
            f" ({result.skipped_large} skipped as too large,"
            f" {result.failed} unreadable)"
            f" -> {counts['symbols']} symbols, {counts['refs']} refs"
            f" in {elapsed:.2f}s"
        )
        print(f"index: {db_path}")
    return 0


def _run_query(args: argparse.Namespace) -> int:
    store = _open_existing(args.repo)
    if store is None:
        return 1
    with store:
        matches = store.lookup_exact(args.name, limit=args.limit)
        if not matches:
            matches = store.search(args.name, limit=args.limit)
    if args.json:
        print(json.dumps([dataclasses.asdict(row) for row in matches]))
        return 0
    if not matches:
        print(f"no matches for {args.name!r}; try grep as a fallback")
        return 0
    for row in matches:
        print(_format_row(row))
    return 0


def _run_stats(args: argparse.Namespace) -> int:
    store = _open_existing(args.repo)
    if store is None:
        return 1
    with store:
        counts = store.stats()
    db_path = repoid.index_path(Path(args.repo).resolve())
    if args.json:
        print(json.dumps({**counts, "db": str(db_path)}))
    else:
        print(
            f"files: {counts['files']}  symbols: {counts['symbols']}"
            f"  refs: {counts['refs']}"
        )
        print(f"index: {db_path}")
    return 0


def _open_existing(repo: str) -> Store | None:
    """Open the index for *repo*, or explain how to create it."""
    repo_root = Path(repo).resolve()
    db_path = repoid.index_path(repo_root)
    if not db_path.exists():
        print(
            f"error: no index for {repo_root};"
            f" run `cidx index --repo {repo_root}` first",
            file=sys.stderr,
        )
        return None
    return Store.open(db_path)


def _format_row(row: SymbolRow) -> str:
    location = f"{row.path}:{row.start_line}"
    line = f"{row.qualified_name}  {row.kind}  {location}"
    if row.signature:
        line += f"  {row.signature}"
    return line
