"""Tests for the agent loop, adapters, and the recorded-response stub."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from benchmark.runners import runner  # noqa: E402
from benchmark.runners import tasks as tasks_mod  # noqa: E402
from benchmark.runners.adapters import CidxAdapter, GrepAdapter  # noqa: E402
from benchmark.runners.model import RecordedStub  # noqa: E402


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "lib.py").write_bytes(
        b"def target_symbol():\n    return 1\n\n\ndef other():\n"
        b"    return target_symbol()\n"
    )
    return root


TASK = tasks_mod.Task(
    id="t-def-target",
    repository="t",
    split="dev",
    question="Where is `target_symbol` defined? Answer with path:line.",
    check={"type": "location", "file": "lib.py", "line_between": [1, 1]},
)


def stub_for(turns: list[dict]) -> RecordedStub:
    stub = RecordedStub(episodes={TASK.id: turns})
    stub.start_episode(TASK.id)
    return stub


class TestAdapters:
    def test_grep_adapter_finds_lines(self, repo: Path) -> None:
        adapter = GrepAdapter()
        adapter.setup(repo)
        try:
            out = adapter.call("grep", {"pattern": r"def target_symbol"})
            assert "lib.py:1:" in out
            assert adapter.call("grep", {"pattern": "zz_none"}) == "no matches"
            assert "invalid pattern" in adapter.call("grep", {"pattern": "("})
        finally:
            adapter.teardown()

    def test_cidx_adapter_serves_definitions(self, repo: Path) -> None:
        adapter = CidxAdapter()
        adapter.setup(repo)
        try:
            out = adapter.call("find_definition", {"name": "target_symbol"})
            assert "lib.py:1" in out
            assert "index_age_ms:" in out
            refs = adapter.call("find_references", {"name": "target_symbol"})
            assert "lib.py:6" in refs
        finally:
            adapter.teardown()


class TestEpisode:
    def test_successful_episode_with_cidx(self, repo: Path) -> None:
        stub = stub_for(
            [
                {
                    "tool_calls": [
                        {
                            "name": "find_definition",
                            "arguments": {"name": "target_symbol"},
                        }
                    ],
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                },
                {
                    "answer": "Defined at lib.py:1.",
                    "prompt_tokens": 150,
                    "completion_tokens": 15,
                },
            ]
        )
        adapter = CidxAdapter()
        adapter.setup(repo)
        log = io.StringIO()
        try:
            result = runner.run_episode(TASK, adapter, stub, repo, log)
        finally:
            adapter.teardown()
        assert result.success
        assert result.total_tokens == 285
        assert result.failure is None

        entries = [json.loads(line) for line in log.getvalue().splitlines()]
        kinds = [e["kind"] for e in entries]
        assert kinds == ["model", "tool", "model", "result"]
        assert entries[-1]["success"] is True

    def test_wrong_answer_is_a_recorded_failure(self, repo: Path) -> None:
        stub = stub_for([{"answer": "It is in other.py:9."}])
        adapter = GrepAdapter()
        adapter.setup(repo)
        log = io.StringIO()
        try:
            result = runner.run_episode(TASK, adapter, stub, repo, log)
        finally:
            adapter.teardown()
        assert not result.success
        assert result.failure is None  # answered, just wrongly

    def test_step_cap_fails_the_task(self, repo: Path) -> None:
        looping = [
            {"tool_calls": [{"name": "grep", "arguments": {"pattern": "def"}}]}
        ] * 30
        stub = stub_for(looping)
        adapter = GrepAdapter()
        adapter.setup(repo)
        log = io.StringIO()
        try:
            result = runner.run_episode(
                TASK, adapter, stub, repo, log, caps=runner.Caps(max_steps=3)
            )
        finally:
            adapter.teardown()
        assert not result.success
        assert result.failure == "step-cap"

    def test_wasted_reads_count_uncited_files(self, repo: Path) -> None:
        stub = stub_for(
            [
                {
                    "tool_calls": [
                        {"name": "read_file", "arguments": {"path": "lib.py"}},
                    ]
                },
                {
                    "tool_calls": [
                        {
                            "name": "final_answer",
                            "arguments": {"text": "Defined at lib.py:1."},
                        }
                    ]
                },
            ]
        )
        adapter = GrepAdapter()
        adapter.setup(repo)
        log = io.StringIO()
        try:
            result = runner.run_episode(TASK, adapter, stub, repo, log)
        finally:
            adapter.teardown()
        assert result.success
        assert result.wasted_reads == 0  # lib.py was read AND cited

    def test_read_file_tool_returns_numbered_window(self, repo: Path) -> None:
        out = runner._read_file(
            repo, {"path": "lib.py", "start_line": 1, "end_line": 2}
        )
        assert out.splitlines() == ["1: def target_symbol():", "2:     return 1"]

    def test_recording_running_dry_fails_honestly(self, repo: Path) -> None:
        stub = stub_for([])  # nothing recorded at all
        adapter = GrepAdapter()
        adapter.setup(repo)
        log = io.StringIO()
        try:
            result = runner.run_episode(TASK, adapter, stub, repo, log)
        finally:
            adapter.teardown()
        assert not result.success
