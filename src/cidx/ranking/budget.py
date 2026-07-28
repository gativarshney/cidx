"""Token budgeting and response shaping.

Every tool response fits a token budget (default ~700 tokens, estimated as
chars/4), and always tells the truth about what it left out: a truncation
marker with the total match count, an index freshness stamp, and — on any
miss — a fail-open message recommending grep, so the worst case with cidx
equals not having it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from cidx.core.store import Store

DEFAULT_MAX_TOKENS = 700


def estimate_tokens(text: str) -> int:
    """chars/4: cheap, deliberately rough, and applied uniformly."""
    return max(1, len(text) // 4) if text else 0


@dataclass(frozen=True, slots=True)
class ShapedResponse:
    """A budgeted, honest response: lines plus the metadata contract."""

    lines: tuple[str, ...]
    truncated: bool
    total_matches: int
    index_age_ms: int
    notes: tuple[str, ...] = field(default=())

    def render(self) -> str:
        """The terse fixed-shape text an agent receives."""
        parts = list(self.lines)
        if self.truncated:
            parts.append(f"truncated: true, total_matches: {self.total_matches}")
        parts.append(f"index_age_ms: {self.index_age_ms}")
        parts.extend(self.notes)
        return "\n".join(parts)


def shape(
    lines: list[str],
    total_matches: int,
    store: Store,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    notes: tuple[str, ...] = (),
) -> ShapedResponse:
    """Trim *lines* to the token budget, never dropping the metadata."""
    kept: list[str] = []
    spent = 0
    for line in lines:
        cost = estimate_tokens(line)
        if kept and spent + cost > max_tokens:
            break
        kept.append(line)
        spent += cost
    truncated = len(kept) < total_matches
    return ShapedResponse(
        lines=tuple(kept),
        truncated=truncated,
        total_matches=total_matches,
        index_age_ms=index_age_ms(store),
        notes=notes,
    )


def index_age_ms(store: Store) -> int:
    """Milliseconds since the most recent file was indexed; 0 for empty."""
    row = store.connection.execute(
        "SELECT MAX(indexed_at) AS newest FROM files"
    ).fetchone()
    if row is None or row["newest"] is None:
        return 0
    return max(0, int((time.time() - row["newest"]) * 1000))


def fail_open_message(reason: str) -> str:
    """The honest miss: say what happened and hand the agent its fallback."""
    return (
        f"cidx: {reason}."
        " Fall back to grep/ripgrep for this question;"
        " results may simply not be indexed yet."
    )
