"""Tests for the ranking features, scorer, and token budgeting contract."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from cidx.core import indexer
from cidx.core.store import Store
from cidx.ranking import budget, features, scorer


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "core.py").write_bytes(
        b"def process():\n    return 1\n\n\n"
        b"def process_all():\n    return [process(), process()]\n\n\n"
        b"def preprocess():\n    return 2\n"
    )
    (root / "other.py").write_bytes(
        b"from pkg.core import process\n\nvalue = process()\nPROCESS_LIMIT = 10\n"
    )
    with Store.open(tmp_path / "cache" / "index.db") as opened:
        indexer.index_repository(root, opened)
        yield opened


class TestFeatures:
    def test_match_tiers_are_assigned_best_first(self, store: Store) -> None:
        by_name = {
            c.row.qualified_name: c
            for c in features.gather_candidates(store, "process")
        }
        assert by_name["process"].match_tier == features.MATCH_EXACT
        assert by_name["process_all"].match_tier == features.MATCH_PREFIX
        # LIKE is case-insensitive: PROCESS_LIMIT counts as a prefix match too
        assert by_name["PROCESS_LIMIT"].match_tier == features.MATCH_PREFIX
        assert by_name["preprocess"].match_tier == features.MATCH_SUBSTRING

    def test_definitions_outweigh_import_bindings(self, store: Store) -> None:
        candidates = features.gather_candidates(store, "process")
        kinds = {c.row.kind: c.kind_weight for c in candidates}
        assert kinds["function"] > kinds["import"]

    def test_popularity_reflects_resolved_references(self, store: Store) -> None:
        by_name = {
            c.row.qualified_name: c
            for c in features.gather_candidates(store, "process")
        }
        # `process` is called three times; `process_all` never
        assert by_name["process"].popularity > by_name["process_all"].popularity

    def test_every_feature_is_normalized(self, store: Store) -> None:
        for candidate in features.gather_candidates(store, "process"):
            assert 0.0 <= candidate.kind_weight <= 1.0
            assert 0.0 <= candidate.popularity <= 1.0
            assert 0.0 <= candidate.locality <= 1.0
            assert 0.0 <= candidate.recency <= 1.0


class TestScorer:
    def test_exact_definition_ranks_first(self, store: Store) -> None:
        rows, total = scorer.search_symbols(store, "process")
        assert rows[0].qualified_name == "process"
        assert rows[0].kind == "function"
        assert total >= 3

    def test_limit_and_total_disagree_when_trimmed(self, store: Store) -> None:
        rows, total = scorer.search_symbols(store, "process", limit=1)
        assert len(rows) == 1
        assert total > 1

    def test_ranking_is_deterministic(self, store: Store) -> None:
        first = [r.id for r in scorer.search_symbols(store, "process")[0]]
        second = [r.id for r in scorer.search_symbols(store, "process")[0]]
        assert first == second


class TestBudget:
    def test_token_estimate_is_chars_over_four(self) -> None:
        assert budget.estimate_tokens("x" * 400) == 100
        assert budget.estimate_tokens("") == 0
        assert budget.estimate_tokens("ab") == 1  # never zero for real text

    def test_lines_fit_the_budget(self, store: Store) -> None:
        lines = [f"symbol_{i}  function  pkg/core.py:{i}" for i in range(500)]
        shaped = budget.shape(lines, total_matches=500, store=store, max_tokens=100)
        spent = sum(budget.estimate_tokens(line) for line in shaped.lines)
        assert spent <= 100
        assert shaped.truncated

    def test_truncation_marker_carries_total_count(self, store: Store) -> None:
        lines = [f"line_{i}" for i in range(50)]
        shaped = budget.shape(lines, total_matches=50, store=store, max_tokens=10)
        rendered = shaped.render()
        assert "truncated: true, total_matches: 50" in rendered
        assert "index_age_ms:" in rendered

    def test_untruncated_response_omits_the_marker(self, store: Store) -> None:
        shaped = budget.shape(["one line"], total_matches=1, store=store)
        assert not shaped.truncated
        assert "truncated" not in shaped.render()

    def test_first_line_survives_even_a_tiny_budget(self, store: Store) -> None:
        shaped = budget.shape(["a" * 400], total_matches=1, store=store, max_tokens=5)
        assert len(shaped.lines) == 1  # never return nothing at all

    def test_index_age_is_non_negative(self, store: Store) -> None:
        assert budget.index_age_ms(store) >= 0

    def test_fail_open_message_recommends_grep(self) -> None:
        message = budget.fail_open_message("no index for this repository")
        assert "grep" in message
        assert "no index" in message
