"""Content hashing for incremental invalidation.

The hash answers one question cheaply: did this file's bytes change since it
was last indexed? It is not a security boundary; BLAKE2b at 16 bytes is fast
and collision-safe far beyond repository scale.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_DIGEST_SIZE = 16
_CHUNK_SIZE = 1 << 16


def content_hash(data: bytes) -> str:
    """Hex digest of *data*, as stored in the index's content_hash column."""
    return hashlib.blake2b(data, digest_size=_DIGEST_SIZE).hexdigest()


def file_hash(path: str | Path) -> str:
    """Hex digest of a file's bytes, streamed so large files stay cheap.

    Raises OSError (FileNotFoundError, PermissionError) as-is; callers decide
    whether a vanished file means "remove from index" or "retry later".
    """
    digest = hashlib.blake2b(digest_size=_DIGEST_SIZE)
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()
