"""Tests for the scorer: every metric recomputed from JSONL alone."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from benchmark.runners import runner, score  # noqa: E402
from benchmark.runners import tasks as tasks_mod  # noqa: E402
from benchmark.runners.adapters import GrepAdapter  # noqa: E402
from benchmark.runners.model import RecordedStub  # noqa: E402

TASK = tasks_mod.Task(
    id="t-def-target",
    repository="t",
    split="dev",
    question="Where is `target_symbol` defined?",
    check={"type": "location", "file": "lib.py", "line_between": [1, 1]},
)
TASK_INDEX = {TASK.id: TASK}


def write_log(tmp_path: Path, lines: list[dict]) -> Path:
    path = tmp_path / "raw.jsonl"
    path.write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )
    return path


def entry(kind: str, contestant: str, rep: int, ts: float, **payload) -> dict:
    return {
        "ts": ts,
        "task": TASK.id,
        "contestant": contestant,
        "rep": rep,
        "step": 0,
        "kind": kind,
        **payload,
    }


class TestRebuild:
    def test_metrics_are_rederived_from_primitive_records(self, tmp_path: Path) -> None:
        log = write_log(
            tmp_path,
            [
                entry(
                    "model", "cidx", 0, 10.0, prompt_tokens=100, completion_tokens=20
                ),
                entry(
                    "tool",
                    "cidx",
                    0,
                    10.4,
                    name="read_file",
                    arguments={"path": "lib.py"},
                    result_chars=50,
                ),
                entry(
                    "tool",
                    "cidx",
                    0,
                    10.5,
                    name="read_file",
                    arguments={"path": "unused.py"},
                    result_chars=50,
                ),
                entry(
                    "model", "cidx", 0, 11.0, prompt_tokens=200, completion_tokens=30
                ),
                entry(
                    "result",
                    "cidx",
                    0,
                    11.5,
                    answer="lib.py:1",
                    failure=None,
                    success=True,
                ),
            ],
        )
        (episode,) = score.rebuild_episodes([log], TASK_INDEX)
        assert episode.success  # re-checked from the answer, not trusted
        assert episode.total_tokens == 350  # re-summed from model records
        assert episode.wasted_reads == 1  # unused.py read but never cited
        assert episode.wall_seconds == 1.5  # from timestamp spread

    def test_runner_summary_is_not_trusted(self, tmp_path: Path) -> None:
        log = write_log(
            tmp_path,
            [
                entry("model", "grep", 0, 1.0, prompt_tokens=10, completion_tokens=1),
                entry(
                    "result",
                    "grep",
                    0,
                    2.0,
                    answer="wrong.py:9",
                    failure=None,
                    success=True,  # runner lies; the scorer re-checks
                ),
            ],
        )
        (episode,) = score.rebuild_episodes([log], TASK_INDEX)
        assert not episode.success

    def test_capped_episode_cannot_succeed(self, tmp_path: Path) -> None:
        log = write_log(
            tmp_path,
            [
                entry("model", "grep", 0, 1.0, prompt_tokens=10, completion_tokens=1),
                entry(
                    "result",
                    "grep",
                    0,
                    2.0,
                    answer="lib.py:1",
                    failure="step-cap",
                    success=False,
                ),
            ],
        )
        (episode,) = score.rebuild_episodes([log], TASK_INDEX)
        assert not episode.success


class TestAggregate:
    def _episodes(self) -> list[score.Episode]:
        make = lambda c, rep, ok, tok: score.Episode(  # noqa: E731
            task_id=TASK.id,
            contestant=c,
            repetition=rep,
            success=ok,
            total_tokens=tok,
            wasted_reads=rep,
            wall_seconds=1.0,
        )
        return [
            make("cidx", 0, True, 100),
            make("cidx", 1, True, 200),
            make("cidx", 2, False, 300),
            make("grep", 0, True, 1000),
            make("grep", 1, False, 3000),
        ]

    def test_success_rate_and_medians(self) -> None:
        cidx, grep = score.aggregate(self._episodes())
        assert cidx.contestant == "cidx"  # better success rate sorts first
        assert cidx.success_rate == pytest.approx(2 / 3, abs=1e-4)
        assert cidx.tokens_median == 200
        assert grep.success_rate == 0.5
        assert grep.tokens_median == 2000

    def test_cost_per_solved_uses_price_and_solved_count(self) -> None:
        stats = score.aggregate(self._episodes(), price_per_million_tokens=10.0)
        cidx = next(s for s in stats if s.contestant == "cidx")
        # 600 total tokens at $10/M = $0.006, over 2 solved
        assert cidx.cost_per_solved == pytest.approx(0.003)

    def test_zero_solved_shows_no_cost_division(self) -> None:
        episodes = [
            score.Episode(TASK.id, "grep", 0, False, 100, 0, 1.0),
        ]
        (stats,) = score.aggregate(episodes, price_per_million_tokens=10.0)
        assert stats.cost_per_solved is None

    def test_table_renders_all_contestants(self) -> None:
        table = score.render_table(score.aggregate(self._episodes()))
        assert "| cidx |" in table
        assert "| grep |" in table
        assert "cost/solved" in table


class TestEndToEndWithRunner:
    def test_scorer_agrees_with_a_real_runner_log(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        (root / "lib.py").write_bytes(b"def target_symbol():\n    return 1\n")
        stub = RecordedStub(
            episodes={TASK.id: [{"answer": "lib.py:1", "prompt_tokens": 50}]}
        )
        stub.start_episode(TASK.id)
        adapter = GrepAdapter()
        adapter.setup(root)
        log = io.StringIO()
        try:
            outcome = runner.run_episode(TASK, adapter, stub, root, log)
        finally:
            adapter.teardown()
        log_path = tmp_path / "raw.jsonl"
        log_path.write_text(log.getvalue(), encoding="utf-8")
        (episode,) = score.rebuild_episodes([log_path], TASK_INDEX)
        assert episode.success == outcome.success is True
        assert episode.total_tokens == outcome.total_tokens == 50
