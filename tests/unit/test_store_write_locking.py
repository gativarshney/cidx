"""Write transactions take the write lock up front (BEGIN IMMEDIATE).

A deferred BEGIN that reads before its first write holds only a read
snapshot. If another connection commits in between, the first write fails
immediately with "database is locked" (SQLITE_BUSY_SNAPSHOT) and the busy
timeout is never consulted, because waiting cannot make a stale snapshot
current. That is how the watcher's consumer thread died on CI while a
test's own connection was finishing schema creation. BEGIN IMMEDIATE takes
the write lock first, so a concurrent writer waits its turn instead.
"""

from __future__ import annotations

import threading
from pathlib import Path

from cidx.core.store import Store
from cidx.extractors.base import Extraction

EMPTY = Extraction(symbols=(), references=())


def test_every_mutation_begins_immediate(tmp_path: Path) -> None:
    statements: list[str] = []
    with Store.open(tmp_path / "index.db") as store:
        store.connection.set_trace_callback(statements.append)
        store.replace_file("a.py", "python", "h1", 0.0, EMPTY)
        store.remove_file("a.py")
        store.resolve_references()
        store.connection.set_trace_callback(None)
    begins = [s for s in statements if s.upper().startswith("BEGIN")]
    assert len(begins) == 3, begins
    assert all(s.upper().startswith("BEGIN IMMEDIATE") for s in begins), (
        f"a deferred BEGIN can fail with SQLITE_BUSY_SNAPSHOT: {begins}"
    )


def test_writer_committing_between_read_and_write_cannot_break_replace(
    tmp_path: Path,
) -> None:
    """Reproduces the CI failure: a second connection commits while
    replace_file has read but not yet written. With a deferred BEGIN the
    write raised "database is locked"; with BEGIN IMMEDIATE the second
    writer waits and both replacements land."""
    db_path = tmp_path / "index.db"
    with Store.open(db_path) as store:
        store.replace_file("seed.py", "python", "h0", 0.0, EMPTY)
        real = store.connection
        fired = threading.Event()
        other_done = threading.Event()

        def other_writer() -> None:  # its own connection: sqlite3 is thread-bound
            with Store.open(db_path) as other:
                other.replace_file("other.py", "python", "h2", 0.0, EMPTY)
            other_done.set()

        class CommitOtherOnFirstRead:
            def __getattr__(self, name: str):
                return getattr(real, name)

            def execute(self, sql: str, *args):
                cursor = real.execute(sql, *args)
                # after the first read: a deferred BEGIN now holds a read
                # snapshot, and the other writer's commit inside this window
                # makes our first write fail; IMMEDIATE already holds the
                # write lock, so the other writer waits instead
                if not fired.is_set() and sql.lstrip().startswith(
                    "SELECT id FROM files"
                ):
                    fired.set()
                    threading.Thread(target=other_writer, daemon=True).start()
                    other_done.wait(2.0)
                return cursor

        store._connection = CommitOtherOnFirstRead()
        try:
            store.replace_file("seed.py", "python", "h1", 0.0, EMPTY)
        finally:
            store._connection = real
        assert fired.is_set()
        assert other_done.wait(35.0), "the concurrent writer never finished"
        assert store.indexed_paths() == {"seed.py", "other.py"}
        assert store.file_record("seed.py")["content_hash"] == "h1"
