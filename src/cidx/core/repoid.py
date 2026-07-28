"""Repository identity and index cache location.

The index never lives inside the user's repository (ADR-003). It is keyed by
a short, stable hash of the repository root's real path and stored under the
per-user cache directory: ``%LOCALAPPDATA%\\cidx`` on Windows, and
``$XDG_CACHE_HOME/cidx`` (default ``~/.cache/cidx``) elsewhere.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

_REPO_ID_LENGTH = 16


def repo_id(repo_root: str | Path) -> str:
    """Stable short identifier for a repository root.

    Built from the root's real path, so symlinked views of one repository
    share one index; case-normalized so Windows path spellings agree.
    """
    normalized = os.path.normcase(os.path.realpath(repo_root))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:_REPO_ID_LENGTH]


def cache_dir() -> Path:
    """The per-user directory that holds every cidx index."""
    return _cache_root(os.name == "nt", os.environ, Path.home())


def index_path(repo_root: str | Path) -> Path:
    """Where the index database for *repo_root* lives (file may not exist yet)."""
    return cache_dir() / repo_id(repo_root) / "index.db"


def _cache_root(is_windows: bool, env: Mapping[str, str], home: Path) -> Path:
    if is_windows:
        local_app_data = env.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else home / "AppData" / "Local"
        return base / "cidx"
    xdg_cache = env.get("XDG_CACHE_HOME")
    # Per the XDG spec, relative XDG_CACHE_HOME values are invalid and ignored.
    # Absoluteness is judged with POSIX semantics: XDG paths are POSIX paths.
    if xdg_cache and PurePosixPath(xdg_cache).is_absolute():
        return Path(xdg_cache) / "cidx"
    return home / ".cache" / "cidx"
