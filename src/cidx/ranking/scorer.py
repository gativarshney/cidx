"""Weighted linear scorer over the engineered feature set.

IMPORTANT — weight discipline (MILESTONES.md, Phase 7): these weights are
deliberately UNTUNED defaults and must stay that way until the benchmark's
dev task split exists. Tuning happens against measurement on the dev split
only, never against vibes, and never against the holdout split.
"""

from __future__ import annotations

from dataclasses import dataclass

from cidx.core.store import Store, SymbolRow
from cidx.ranking import features
from cidx.ranking.features import Candidate


@dataclass(frozen=True, slots=True)
class Weights:
    """The scorer's configuration surface; defaults are untuned placeholders."""

    match_tier: float = 3.0
    kind: float = 1.0
    popularity: float = 1.0
    locality: float = 0.5
    recency: float = 0.5


DEFAULT_WEIGHTS = Weights()


def score(candidate: Candidate, weights: Weights = DEFAULT_WEIGHTS) -> float:
    """The weighted linear combination; higher is better."""
    return (
        weights.match_tier * (candidate.match_tier / features.MATCH_EXACT)
        + weights.kind * candidate.kind_weight
        + weights.popularity * candidate.popularity
        + weights.locality * candidate.locality
        + weights.recency * candidate.recency
    )


def rank(
    candidates: list[Candidate], weights: Weights = DEFAULT_WEIGHTS
) -> list[Candidate]:
    """Best first; ties break on values (path, line), never on ids."""
    return sorted(
        candidates,
        key=lambda c: (-score(c, weights), c.row.path, c.row.start_line),
    )


def search_symbols(
    store: Store,
    text: str,
    limit: int = 20,
    weights: Weights = DEFAULT_WEIGHTS,
) -> tuple[list[SymbolRow], int]:
    """Ranked symbol search: (top rows, total match count before the limit)."""
    candidates = features.gather_candidates(store, text)
    ranked = rank(candidates, weights)
    return [candidate.row for candidate in ranked[:limit]], len(ranked)
