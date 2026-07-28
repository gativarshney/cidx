"""The ranking feature set: engineered signals, no ML, no embeddings.

Features (ARCHITECTURE.md): match tier (exact > prefix > substring > FTS),
symbol kind (definitions over bindings), popularity (log-scaled resolved
reference count — a one-step PageRank approximation), path locality to
recently touched files, and edit recency. Every feature is normalized to
[0, 1] so the linear scorer's weights stay comparable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from cidx.core.store import Store, SymbolRow

MATCH_EXACT = 3
MATCH_PREFIX = 2
MATCH_SUBSTRING = 1
MATCH_FTS = 0

_KIND_WEIGHTS = {
    "function": 1.0,
    "class": 1.0,
    "method": 0.9,
    "const": 0.6,
    "import": 0.3,
}

_RECENT_FILE_COUNT = 20


@dataclass(frozen=True, slots=True)
class Candidate:
    """One symbol under consideration, with its normalized features."""

    row: SymbolRow
    match_tier: int
    kind_weight: float
    popularity: float
    locality: float
    recency: float


def gather_candidates(store: Store, text: str, limit: int = 200) -> list[Candidate]:
    """Collect and featurize match candidates for *text*, best tier per symbol."""
    tiers: dict[int, int] = {}
    rows: dict[int, SymbolRow] = {}

    def record(matches: list[SymbolRow], tier: int) -> None:
        for row in matches:
            rows.setdefault(row.id, row)
            tiers[row.id] = max(tiers.get(row.id, MATCH_FTS), tier)

    record(store.lookup_exact(text, limit=limit), MATCH_EXACT)
    record(_like(store, text + "%", limit), MATCH_PREFIX)
    record(_like(store, "%" + text + "%", limit), MATCH_SUBSTRING)
    record(store.search(text, limit=limit), MATCH_FTS)
    if not rows:
        return []

    popularity = _popularity_by_symbol(store, list(rows))
    max_popularity = max(popularity.values(), default=0.0) or 1.0
    recent = _recently_touched_paths(store)
    mtime_rank = _mtime_rank_by_path(store)
    return [
        Candidate(
            row=row,
            match_tier=tiers[symbol_id],
            kind_weight=_KIND_WEIGHTS.get(row.kind, 0.5),
            popularity=popularity.get(symbol_id, 0.0) / max_popularity,
            locality=_locality(row.path, recent),
            recency=mtime_rank.get(row.path, 0.0),
        )
        for symbol_id, row in rows.items()
    ]


def _like(store: Store, pattern: str, limit: int) -> list[SymbolRow]:
    rows = store.connection.execute(
        "SELECT s.id, s.name, s.qualified_name, s.kind, f.path,"
        " s.start_line, s.end_line, s.signature"
        " FROM symbols s JOIN files f ON f.id = s.file_id"
        " WHERE s.name LIKE ? ESCAPE '\\'"
        " ORDER BY f.path, s.start_line LIMIT ?",
        (pattern, limit),
    ).fetchall()
    return [SymbolRow(**row) for row in rows]


def _popularity_by_symbol(store: Store, symbol_ids: list[int]) -> dict[int, float]:
    """Log-scaled resolved-reference counts: the one-step PageRank stand-in."""
    placeholders = ", ".join("?" for _ in symbol_ids)
    counts = store.connection.execute(
        "SELECT resolved_symbol_id AS sid, COUNT(*) AS n FROM refs"
        f" WHERE resolved_symbol_id IN ({placeholders}) GROUP BY resolved_symbol_id",
        symbol_ids,
    ).fetchall()
    return {row["sid"]: math.log1p(row["n"]) for row in counts}


def _recently_touched_paths(store: Store) -> list[str]:
    rows = store.connection.execute(
        "SELECT path FROM files ORDER BY mtime DESC LIMIT ?",
        (_RECENT_FILE_COUNT,),
    ).fetchall()
    return [row["path"] for row in rows]


def _mtime_rank_by_path(store: Store) -> dict[str, float]:
    """Path -> normalized recency in [0, 1]; the newest file scores 1."""
    rows = store.connection.execute(
        "SELECT path FROM files ORDER BY mtime ASC"
    ).fetchall()
    if not rows:
        return {}
    denominator = max(len(rows) - 1, 1)
    return {row["path"]: index / denominator for index, row in enumerate(rows)}


def _locality(path: str, recent_paths: list[str]) -> float:
    """Best directory-prefix overlap with any recently touched file."""
    parts = path.split("/")[:-1]
    best = 0.0
    for recent in recent_paths:
        recent_parts = recent.split("/")[:-1]
        shared = 0
        for a, b in zip(parts, recent_parts, strict=False):
            if a != b:
                break
            shared += 1
        longest = max(len(parts), len(recent_parts), 1)
        best = max(best, shared / longest)
        if recent == path:
            return 1.0
    return best
