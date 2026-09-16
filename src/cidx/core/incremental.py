"""Incremental engine: the index must always equal a cold rebuild.

Per changed path: stat and hash; unchanged content stops the pipeline (free).
Otherwise parse, extract, and swap the file's rows in one transaction
(``Store.replace_file``). Deletes and renames arrive as the same machinery: a
vanished, oversized, or unsupported path simply has its rows removed.

Callers that already know a path is eligible and that will resolve once at
the end of a batch (the watcher's reconciliation sweep) pass
``check_ignored=False`` and ``resolve=False``. Both default to True, so a
single-path refresh stays self-contained and immediately queryable; skipping
them in a batch is what keeps a full sweep O(n) instead of O(n^2), because
``resolve_references`` is a whole-index recompute (ADR-015).

``check_drift`` proves the invariant on demand: cold-rebuild into a temporary
database, diff value-level row multisets, report every differing row exactly.
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
    *,
    resolve: bool = True,
    check_ignored: bool = True,
) -> Outcome:
    """Bring one path's index rows up to date with the filesystem.

    Returns what happened: ``unchanged`` (hash matched, free), ``updated``
    (rows swapped), ``removed`` (path gone/unsupported/oversized and its rows
    dropped), or ``absent`` (nothing on disk and nothing indexed).

    ``resolve=False`` skips the whole-index resolution recompute, and
    ``check_ignored=False`` skips the ``git check-ignore`` subprocess. Both
    are safe only for a caller that discovered the path through
    ``iter_source_files`` and resolves once after the batch; see ADR-015.
    """
    rel = Path(relative_path).as_posix()
    root_path = Path(root)
    absolute = root_path / rel
    known = store.file_record(rel)

    data: bytes | None = None
    language_id = base.detect_language(absolute)
    if language_id is not None and check_ignored and indexer.is_ignored(root_path, rel):
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
        if resolve:
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
    if resolve:
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
    """Diff the live index against a cold rebuild; empty means converged.

    Snapshots are multisets, so a row present twice in one and once in the
    other is reported once, with the surplus copy listed as missing or extra.
    """
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
                    missing=tuple(sorted(missing.elements(), key=repr)),
                    extra=tuple(sorted(extra.elements(), key=repr)),
                )
            )
    return drifts
