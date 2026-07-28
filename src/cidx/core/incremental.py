"""Incremental engine: the index must always equal a cold rebuild.

Per changed path: stat and hash; unchanged content stops the pipeline (free).
Otherwise parse, extract, and swap the file's rows in one transaction
(``Store.replace_file``). Deletes and renames arrive as the same machinery: a
vanished, oversized, or unsupported path simply has its rows removed.

``check_drift`` proves the invariant on demand: cold-rebuild into a temporary
database, diff value-level row sets, report every differing row exactly.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cidx.core import hashing, indexer
from cidx.core.store import Store
from cidx.extractors import base

Outcome = Literal["unchanged", "updated", "removed", "absent"]


def refresh_path(
    store: Store,
    root: str | Path,
    relative_path: str,
    max_file_bytes: int = indexer.DEFAULT_MAX_FILE_BYTES,
) -> Outcome:
    """Bring one path's index rows up to date with the filesystem.

    Returns what happened: ``unchanged`` (hash matched, free), ``updated``
    (rows swapped), ``removed`` (path gone/unsupported/oversized and its rows
    dropped), or ``absent`` (nothing on disk and nothing indexed).
    """
    rel = Path(relative_path).as_posix()
    root_path = Path(root)
    absolute = root_path / rel
    known = store.file_record(rel)

    data: bytes | None = None
    language_id = base.detect_language(absolute)
    if language_id is not None and indexer.is_ignored(root_path, rel):
        language_id = None  # discovery would never list it: treat as gone
    if language_id is not None:
        try:
            stat = absolute.stat()
            if stat.st_size <= max_file_bytes:
                data = absolute.read_bytes()
        except OSError:
            data = None  # vanished, unreadable, or a directory: treat as gone

    if data is None:
        if known is None:
            return "absent"
        store.remove_file(rel)
        store.resolve_references()
        return "removed"

    digest = hashing.content_hash(data)
    if known is not None and known["content_hash"] == digest:
        return "unchanged"
    store.replace_file(
        rel,
        language_id,
        digest,
        stat.st_mtime,
        indexer.extract_source(data, language_id),
    )
    store.resolve_references()
    return "updated"


@dataclass(frozen=True, slots=True)
class Drift:
    """Row-level disagreement between the live index and a cold rebuild."""

    table: str
    missing: tuple[tuple, ...]  # rows a cold rebuild produces but live lacks
    extra: tuple[tuple, ...]  # rows live holds but a cold rebuild would not


def check_drift(
    root: str | Path,
    store: Store,
    max_file_bytes: int = indexer.DEFAULT_MAX_FILE_BYTES,
) -> list[Drift]:
    """Diff the live index against a cold rebuild; empty means converged."""
    with tempfile.TemporaryDirectory(prefix="cidx-check-") as tmp:
        with Store.open(Path(tmp) / "check.db") as fresh:
            indexer.index_repository(root, fresh, max_file_bytes)
            expected = fresh.snapshot()
    actual = store.snapshot()
    drifts: list[Drift] = []
    for table in ("files", "symbols", "refs"):
        missing = expected[table] - actual[table]
        extra = actual[table] - expected[table]
        if missing or extra:
            drifts.append(
                Drift(
                    table=table,
                    missing=tuple(sorted(missing, key=repr)),
                    extra=tuple(sorted(extra, key=repr)),
                )
            )
    return drifts
