"""Tests for the benchmark task suite: schema, split, and machine checks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from benchmark.runners import tasks as tasks_mod  # noqa: E402

REPOS_DIR = REPO_ROOT / "benchmark" / "datasets" / "repos"


@pytest.fixture(scope="module")
def suite() -> list[tasks_mod.Task]:
    return tasks_mod.load_tasks()


class TestCommittedSuite:
    def test_task_count_is_in_the_documented_range(
        self, suite: list[tasks_mod.Task]
    ) -> None:
        assert 30 <= len(suite) <= 50

    def test_ids_are_unique_and_prefixed_by_repository(
        self, suite: list[tasks_mod.Task]
    ) -> None:
        assert len({t.id for t in suite}) == len(suite)
        for task in suite:
            assert task.id.startswith(task.repository)

    def test_split_covers_both_sides_sensibly(
        self, suite: list[tasks_mod.Task]
    ) -> None:
        holdout = sum(1 for t in suite if t.split == "holdout")
        assert 0.2 <= holdout / len(suite) <= 0.4  # split fixed at authoring

    def test_every_repository_contributes_tasks(
        self, suite: list[tasks_mod.Task]
    ) -> None:
        assert {t.repository for t in suite} == {"click", "flask", "express", "zod"}

    @pytest.mark.skipif(not REPOS_DIR.exists(), reason="pinned repos not materialized")
    def test_location_ground_truth_files_exist_in_pinned_checkouts(
        self, suite: list[tasks_mod.Task]
    ) -> None:
        for task in suite:
            if task.check["type"] != "location":
                continue
            checkout = REPOS_DIR / task.repository / task.check["file"]
            assert checkout.is_file(), f"{task.id}: {task.check['file']} missing"


class TestValidation:
    def test_bad_split_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "bad.json").write_text(
            '{"repository": "x", "tasks": [{"id": "x-1", "split": "test",'
            ' "question": "q?", "check": {"type": "regex", "pattern": "a"}}]}',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="bad split"):
            tasks_mod.load_tasks(tmp_path)

    def test_duplicate_ids_are_rejected(self, tmp_path: Path) -> None:
        entry = (
            '{"id": "x-1", "split": "dev", "question": "q?",'
            ' "check": {"type": "regex", "pattern": "a"}}'
        )
        (tmp_path / "bad.json").write_text(
            f'{{"repository": "x", "tasks": [{entry}, {entry}]}}',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="duplicate task ids"):
            tasks_mod.load_tasks(tmp_path)


class TestCheckAnswer:
    def _task(self, check: dict) -> tasks_mod.Task:
        return tasks_mod.Task(
            id="t-1", repository="t", split="dev", question="q?", check=check
        )

    def test_location_with_line_window(self) -> None:
        task = self._task(
            {"type": "location", "file": "src/app.py", "line_between": [10, 14]}
        )
        assert tasks_mod.check_answer(task, "It is defined at src/app.py:12.")
        assert tasks_mod.check_answer(task, "src\\app.py:10 (Windows citation)")
        assert not tasks_mod.check_answer(task, "src/app.py:99 is the spot")
        assert not tasks_mod.check_answer(task, "somewhere in src/app.py")
        assert not tasks_mod.check_answer(task, "no idea")

    def test_location_file_only(self) -> None:
        task = self._task({"type": "location", "file": "lib/view.js"})
        assert tasks_mod.check_answer(task, "The View class lives in lib/view.js.")
        assert not tasks_mod.check_answer(task, "lib/application.js")

    def test_contains_all_requires_every_value(self) -> None:
        task = self._task({"type": "contains_all", "values": ["a.py", "b.py"]})
        assert tasks_mod.check_answer(task, "Both a.py and b.py define it.")
        assert not tasks_mod.check_answer(task, "Only a.py defines it.")

    def test_regex_answers(self) -> None:
        task = self._task({"type": "regex", "pattern": "\\bUsageError\\b"})
        assert tasks_mod.check_answer(task, "It extends UsageError.")
        assert not tasks_mod.check_answer(task, "It extends MyUsageErrorBase.")
