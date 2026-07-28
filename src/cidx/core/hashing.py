"""Content hashing for incremental invalidation.

The hash answers one question cheaply: did this file's bytes change since it
was last indexed? It is not a security boundary; BLAKE2b at 16 bytes is fast
and collision-safe far beyond repository scale.
"""

from __future__ import annotations

import hashlib

_DIGEST_SIZE = 16


def content_hash(data: bytes) -> str:
    """Hex digest of *data*, as stored in the index's content_hash column."""
    return hashlib.blake2b(data, digest_size=_DIGEST_SIZE).hexdigest()
