"""Real-time index freshness: watchdog producer, indexer consumer.

The producer thread (a watchdog observer) filters raw filesystem events and
puts repo-relative paths on a queue. The consumer thread drains the queue,
debounces ~100ms per path, coalesces duplicates to one pending entry per
path, drops git-ignored paths, and runs the incremental engine. The consumer
owns its own SQLite connection; WAL mode lets other threads read while it
writes.

OS watchers drop events under storms, so a periodic reconciliation sweep
re-stats and re-hashes everything cheaply (the hash short-circuit makes
unchanged files free) and removes indexed paths that discovery no longer
lists: fast path for speed, slow path for truth.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from cidx.core import incremental, indexer
from cidx.core.store import Store

DEFAULT_DEBOUNCE_SECONDS = 0.1
DEFAULT_SWEEP_INTERVAL_SECONDS = 30.0


class _EventHandler(FileSystemEventHandler):
    def __init__(self, watcher: Watcher) -> None:
        self._watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return  # directory renames are reconciled by the sweep
        for raw_path in (event.src_path, getattr(event, "dest_path", "")):
            if raw_path:
                self._watcher.enqueue(str(raw_path))


class Watcher:
    """Keeps one repository's index fresh until stopped."""

    def __init__(
        self,
        root: str | Path,
        db_path: str | Path,
        *,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        sweep_interval_seconds: float = DEFAULT_SWEEP_INTERVAL_SECONDS,
        max_file_bytes: int = indexer.DEFAULT_MAX_FILE_BYTES,
    ) -> None:
        self._root = Path(root).resolve()
        self._db_path = Path(db_path)
        self._debounce = debounce_seconds
        self._sweep_interval = sweep_interval_seconds
        self._max_file_bytes = max_file_bytes
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._observer = Observer()
        self._consumer = threading.Thread(
            target=self._consume, name="cidx-indexer", daemon=True
        )

    def start(self) -> None:
        """Start watching; an immediate reconciliation sweep aligns the index."""
        self._observer.schedule(_EventHandler(self), str(self._root), recursive=True)
        self._observer.start()
        self._consumer.start()

    def stop(self) -> None:
        """Stop both threads and wait for them; safe to call twice."""
        self._stop_event.set()
        self._queue.put(None)  # wake the consumer
        if self._observer.is_alive():
            self._observer.stop()
            self._observer.join()
        if self._consumer.is_alive():
            self._consumer.join()

    def enqueue(self, raw_path: str) -> None:
        """Producer side: cheap filter, then hand the path to the consumer."""
        try:
            relative = Path(raw_path).resolve().relative_to(self._root)
        except (OSError, ValueError):
            return  # outside the watched root
        if any(part in indexer._ALWAYS_IGNORED_DIRS for part in relative.parts):
            return
        self._queue.put(relative.as_posix())

    # --- consumer thread ---------------------------------------------------

    def _consume(self) -> None:
        with Store.open(self._db_path) as store:
            pending: dict[str, float] = {}  # path -> moment it may be processed
            next_sweep = time.monotonic()  # first loop turn sweeps immediately
            while not self._stop_event.is_set():
                timeout = (
                    0.02
                    if pending
                    else min(max(next_sweep - time.monotonic(), 0.02), 0.5)
                )
                try:
                    item = self._queue.get(timeout=timeout)
                    if item is not None:
                        pending[item] = time.monotonic() + self._debounce
                except queue.Empty:
                    pass
                now = time.monotonic()
                ready = [path for path, due in pending.items() if due <= now]
                if ready:
                    for path in ready:
                        del pending[path]
                        # gitignored paths are refused by the engine itself
                        # (indexer.is_ignored inside refresh_path)
                        incremental.refresh_path(
                            store, self._root, path, self._max_file_bytes
                        )
                if now >= next_sweep:
                    self._sweep(store)
                    next_sweep = time.monotonic() + self._sweep_interval

    def _sweep(self, store: Store) -> None:
        """Slow path for truth: converge the index with discovery's listing."""
        on_disk = {
            path.relative_to(self._root).as_posix()
            for path in indexer.iter_source_files(self._root)
        }
        for stale in store.indexed_paths() - on_disk:
            if self._stop_event.is_set():
                return
            store.remove_file(stale)
        for path in on_disk:
            if self._stop_event.is_set():
                return
            incremental.refresh_path(store, self._root, path, self._max_file_bytes)
        # even an all-unchanged sweep re-resolves: hash short-circuits skip
        # resolution, and truth includes resolved targets
        store.resolve_references()
