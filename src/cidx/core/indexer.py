"""Cold indexer: one full repository walk into the store.

File discovery honors ``.gitignore`` exactly when git is available, by asking
``git ls-files`` for tracked plus untracked-but-not-ignored files. Without
git (no ``.git`` directory, or no git on PATH) it falls back to a filesystem
walk that skips well-known junk directories. Files above the size cap and
files cidx has no grammar for are skipped either way.

Paths are stored repo-relative with forward slashes so an index is readable
on every platform.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from cidx.core import hashing
from cidx.core.store import Store
from cidx.extractors import base, python, typescript
from cidx.extractors.base import Extraction

DEFAULT_MAX_FILE_BYTES = 1_048_576  # 1 MiB: bigger files are generated, not code

_FALLBACK_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
    }
)


@dataclass(frozen=True, slots=True)
class IndexResult:
    """What one cold index run did."""

    indexed: int
    skipped_large: int
    failed: int
    removed: int = 0


def index_repository(
    root: str | Path,
    store: Store,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> IndexResult:
    """Walk *root* and reconcile *store* with it: index every discovered
    source file, and remove rows for paths discovery no longer lists
    (deleted, newly gitignored, or renamed away)."""
    root_path = Path(root).resolve()
    indexed = skipped_large = failed = 0
    present: set[str] = set()  # paths that ended this walk with rows
    for path in iter_source_files(root_path):
        relative = path.relative_to(root_path).as_posix()
        try:
            stat = path.stat()
            if stat.st_size > max_file_bytes:
                skipped_large += 1
                continue
            source = path.read_bytes()
        except OSError:
            failed += 1  # vanished or unreadable mid-walk: skip, stay consistent
            continue
        language_id = base.detect_language(path)
        assert language_id is not None  # iter_source_files only yields supported
        store.replace_file(
            relative,
            language_id,
            hashing.content_hash(source),
            stat.st_mtime,
            extract_source(source, language_id),
        )
        present.add(relative)
        indexed += 1
    # reconcile: anything indexed earlier but not successfully indexed on
    # THIS walk (deleted, renamed, newly gitignored, grown past the cap)
    # would not exist in a cold rebuild, so its rows must go
    stale = store.indexed_paths() - present
    for path_gone in sorted(stale):
        store.remove_file(path_gone)
    store.resolve_references()  # once, after the walk: O(repo), not O(repo^2)
    return IndexResult(
        indexed=indexed,
        skipped_large=skipped_large,
        failed=failed,
        removed=len(stale),
    )


def iter_source_files(root: Path) -> Iterator[Path]:
    """Every indexable file under *root*, .gitignore-aware when git works."""
    listed = _git_listed_paths(root)
    if listed is not None:
        for relative in listed:
            path = root / relative
            if base.detect_language(path) is not None and path.is_file():
                yield path
        return
    yield from _walk(root)


def _git_listed_paths(root: Path) -> list[str] | None:
    """Repo-relative paths from git, or None when git cannot answer."""
    if not (root / ".git").exists():
        return None
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    listing = completed.stdout.decode("utf-8", errors="replace")
    return [entry for entry in listing.split("\0") if entry]


def _walk(root: Path) -> Iterator[Path]:
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.is_dir():
            if entry.name not in _FALLBACK_IGNORED_DIRS:
                yield from _walk(entry)
        elif base.detect_language(entry) is not None:
            yield entry


def is_ignored(root: Path, relative_posix: str) -> bool:
    """Would discovery skip this path? The incremental engine asks this so a
    watcher event (or any direct refresh) can never index a file that a cold
    rebuild would exclude.

    Junk directories are checked first (cheap); gitignore semantics come from
    ``git check-ignore`` when the repo has one. A git failure fails open —
    exactly like discovery's own fallback.
    """
    directories = relative_posix.split("/")[:-1]
    if any(part in _FALLBACK_IGNORED_DIRS for part in directories):
        return True
    if not (root / ".git").exists():
        return False
    try:
        completed = subprocess.run(
            ["git", "check-ignore", "-q", "--", relative_posix],
            cwd=root,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def extract_source(source: bytes, language_id: str) -> Extraction:
    """Dispatch to the right extractor; shared by cold and incremental paths."""
    if language_id == base.PYTHON:
        return python.extract(source)
    return typescript.extract(source, language_id)
