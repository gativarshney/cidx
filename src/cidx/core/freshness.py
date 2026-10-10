"""Detect cited files whose bytes changed after they were indexed.

The freshness stamp (``index_age_ms``) says how long ago the index was last
written; it cannot say whether the disk has moved on since. With nothing
watching — ``cidx query`` between runs, or ``cidx serve`` before its first
sweep catches up — the index can cite a file that was edited or deleted, and
an agent would trust a line number that is no longer true. Every answer
therefore re-checks the files it is about to cite: one ``stat`` per file,
and a hash only when the modification time no longer matches. The cost is
bounded by the number of cited files, never by the repository (ADR-018).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from cidx.core import hashing
from cidx.core.store import Store


def changed_paths(store: Store, root: str | Path, paths: Iterable[str]) -> list[str]:
    """Cited repo-relative paths whose on-disk bytes differ from the index.

    A path counts as changed when it is missing, unreadable, or its content
    hash no longer matches. A touched-but-identical file (new mtime, same
    bytes) does not. Paths the index does not hold are ignored. Each path is
    checked once; the result keeps first-appearance order.
    """
    root_path = Path(root)
    changed: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        record = store.file_record(path)
        if record is None:
            continue
        absolute = root_path / path
        try:
            if absolute.stat().st_mtime == record["mtime"]:
                continue  # same mtime as when indexed: the common, free case
            data = absolute.read_bytes()
        except OSError:
            changed.append(path)  # deleted, unreadable, or now a directory
            continue
        if hashing.content_hash(data) != record["content_hash"]:
            changed.append(path)
    return changed
