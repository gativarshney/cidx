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
from collections.abc import Callable, Sequence
from importlib.metadata import version
from pathlib import Path

from cidx.core import incremental, indexer, query, repoid
from cidx.core.query import OutlineRow, ReferenceRow, RepoMapEntry
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
        "query", help="look up definitions, references, outlines, or the repo map"
    )
    query.add_argument(
        "name",
        nargs="?",
        help="symbol name or qualified name; a file path with --outline",
    )
    mode = query.add_mutually_exclusive_group()
    mode.add_argument(
        "--references", action="store_true", help="usage sites instead of definitions"
    )
    mode.add_argument("--outline", action="store_true", help="every symbol in one file")
    mode.add_argument(
        "--repo-map", action="store_true", help="repository shape by popularity"
    )
    query.add_argument(
        "--limit", type=int, default=20, help="maximum results (default 20)"
    )
    _add_common_arguments(query)

    stats = subparsers.add_parser("stats", help="show index size and location")
    _add_common_arguments(stats)

    check = subparsers.add_parser(
        "check", help="verify the index exactly matches a cold rebuild"
    )
    _add_common_arguments(check)

    serve = subparsers.add_parser(
        "serve", help="run the MCP server over stdio, keeping the index fresh"
    )
    _add_common_arguments(serve)

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
    if args.command == "check":
        return _run_check(args)
    if args.command == "serve":
        return _run_serve(args)
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
    if args.name is None and not args.repo_map:
        print("error: a name is required unless using --repo-map", file=sys.stderr)
        return 2
    store = _open_existing(args.repo)
    if store is None:
        return 1
    with store:
        if args.repo_map:
            return _emit(
                args,
                query.repo_map(store, limit=args.limit),
                _format_map_entry,
                "repo map is empty; run `cidx index` first",
            )
        if args.outline:
            return _emit(
                args,
                query.outline_file(store, Path(args.name).as_posix()),
                _format_outline_row,
                f"no symbols for {args.name!r}; is the path repo-relative?",
            )
        if args.references:
            return _emit(
                args,
                query.find_references(store, args.name, limit=args.limit),
                _format_reference_row,
                f"no references to {args.name!r}; try grep as a fallback",
            )
        matches: list = query.find_definition(store, args.name, limit=args.limit)
        if not matches:
            matches = store.search(args.name, limit=args.limit)
        return _emit(
            args,
            matches,
            _format_row,
            f"no matches for {args.name!r}; try grep as a fallback",
        )


def _emit(
    args: argparse.Namespace,
    rows: list,
    format_row: Callable[..., str],
    empty_message: str,
) -> int:
    if args.json:
        print(json.dumps([dataclasses.asdict(row) for row in rows]))
        return 0
    if not rows:
        print(empty_message)
        return 0
    for row in rows:
        print(format_row(row))
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


def _run_check(args: argparse.Namespace) -> int:
    store = _open_existing(args.repo)
    if store is None:
        return 1
    with store:
        drifts = incremental.check_drift(Path(args.repo).resolve(), store)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "table": d.table,
                        "missing": [list(row) for row in d.missing],
                        "extra": [list(row) for row in d.extra],
                    }
                    for d in drifts
                ]
            )
        )
        return 0 if not drifts else 1
    if not drifts:
        print("no drift: the index matches a cold rebuild")
        return 0
    for drift in drifts:
        for row in drift.missing:
            print(f"{drift.table}: missing from index: {row}")
        for row in drift.extra:
            print(f"{drift.table}: stale in index: {row}")
    print("drift detected; run `cidx index` to rebuild, and please report this")
    return 1


def _run_serve(args: argparse.Namespace) -> int:
    from cidx.core.watcher import Watcher
    from cidx.mcp.server import create_server

    repo_root = Path(args.repo).resolve()
    if not repo_root.is_dir():
        print(f"error: {repo_root} is not a directory", file=sys.stderr)
        return 1
    db_path = repoid.index_path(repo_root)
    # the watcher's immediate first sweep builds or refreshes the index,
    # so a cold start still serves (increasingly complete) answers
    watcher = Watcher(repo_root, db_path)
    watcher.start()
    try:
        create_server(repo_root, db_path).run()
    finally:
        watcher.stop()
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


def _format_reference_row(row: ReferenceRow) -> str:
    line = f"{row.path}:{row.line}  {row.name}  [{row.confidence}]"
    if row.resolved_qualified_name:
        line += f"  -> {row.resolved_qualified_name} ({row.resolved_path})"
    return line


def _format_outline_row(row: OutlineRow) -> str:
    indent = "  " * (row.parent.count(".") + 1 if row.parent else 0)
    detail = row.signature or row.qualified_name
    return f"{row.start_line:>5}  {indent}{row.name}  {row.kind}  {detail}"


def _format_map_entry(entry: RepoMapEntry) -> str:
    top = ", ".join(entry.top_symbols) or "-"
    return (
        f"{entry.path}  ({entry.language}, {entry.symbol_count} symbols,"
        f" {entry.incoming_refs} inbound)  {top}"
    )
