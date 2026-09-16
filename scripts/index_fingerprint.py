"""Print a platform-independent fingerprint of a repository's cidx index.

The fingerprint is a SHA-256 over the index's value-level snapshot (the same
rows ``cidx check`` compares: files, symbols, references with resolved
targets; no row ids, no timestamps; paths are repository-relative with
forward slashes). Two machines that index the same repository revision and
print the same digest produced byte-for-byte identical index contents. Used
by the cross-platform workflow to compare Linux and Windows.

Usage::

    cidx index --repo path/to/repo
    python scripts/index_fingerprint.py --repo path/to/repo [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from cidx.core import repoid
from cidx.core.store import Store


def fingerprint(store: Store) -> tuple[dict[str, int], str]:
    """(row counts per table, hex digest) of the store's snapshot."""
    snapshot = store.snapshot()
    digest = hashlib.sha256()
    counts: dict[str, int] = {}
    for table in ("files", "symbols", "refs"):
        rows = sorted(snapshot[table].elements(), key=repr)
        counts[table] = len(rows)
        for row in rows:
            digest.update(repr(row).encode("utf-8"))
            digest.update(b"\n")
    return counts, digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=".", help="repository root (default: .)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    db_path = repoid.index_path(Path(args.repo).resolve())
    if not db_path.exists():
        print(f"error: no index at {db_path}; run `cidx index` first", file=sys.stderr)
        return 1
    with Store.open(db_path) as store:
        counts, digest = fingerprint(store)
    if args.json:
        print(json.dumps({**counts, "sha256": digest}))
    else:
        print(
            f"files={counts['files']} symbols={counts['symbols']}"
            f" refs={counts['refs']} sha256={digest}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
