"""Task loading, validation, and machine checking.

Tasks live in ``benchmark/tasks/<repo>.json`` (one file per pinned repo, JSON
by owner decision 2026-07-28) with a dev/holdout split fixed at authoring
time. Ground truth is machine-checkable only: a file location (optionally
with a line window), a set of required substrings, or a regex — never
free-text judged by a model.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

TASKS_DIR = Path(__file__).resolve().parent.parent / "tasks"

_CHECK_TYPES = frozenset({"location", "contains_all", "regex"})
_SPLITS = frozenset({"dev", "holdout"})


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    repository: str
    split: str
    question: str
    check: dict


def load_tasks(tasks_dir: Path = TASKS_DIR) -> list[Task]:
    """Load and validate every task file; raises ValueError on bad tasks."""
    tasks: list[Task] = []
    for path in sorted(tasks_dir.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        repository = document["repository"]
        for entry in document["tasks"]:
            task = Task(
                id=entry["id"],
                repository=repository,
                split=entry["split"],
                question=entry["question"],
                check=entry["check"],
            )
            _validate(task, path)
            tasks.append(task)
    ids = [task.id for task in tasks]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate task ids: {sorted(duplicates)}")
    return tasks


def check_answer(task: Task, answer: str) -> bool:
    """The machine check: did *answer* contain the ground truth?"""
    check = task.check
    kind = check["type"]
    if kind == "regex":
        return re.search(check["pattern"], answer) is not None
    if kind == "contains_all":
        return all(value in _normalized(answer) for value in check["values"])
    # location: the file path must be cited; with a line window, some cited
    # line for that file must fall inside it
    normalized = _normalized(answer)
    file = check["file"]
    if file not in normalized:
        return False
    window = check.get("line_between")
    if window is None:
        return True
    low, high = window
    for match in re.finditer(re.escape(file) + r"(?::|, line |#L)(\d+)", normalized):
        if low <= int(match.group(1)) <= high:
            return True
    return False


def _normalized(answer: str) -> str:
    return answer.replace("\\", "/")


def _validate(task: Task, source: Path) -> None:
    if task.split not in _SPLITS:
        raise ValueError(f"{source.name}:{task.id}: bad split {task.split!r}")
    kind = task.check.get("type")
    if kind not in _CHECK_TYPES:
        raise ValueError(f"{source.name}:{task.id}: bad check type {kind!r}")
    if kind == "location":
        if "file" not in task.check:
            raise ValueError(f"{source.name}:{task.id}: location needs a file")
        window = task.check.get("line_between")
        if window is not None and (
            len(window) != 2 or window[0] > window[1] or window[0] < 1
        ):
            raise ValueError(f"{source.name}:{task.id}: bad line window {window}")
    elif kind == "contains_all" and not task.check.get("values"):
        raise ValueError(f"{source.name}:{task.id}: contains_all needs values")
    elif kind == "regex" and "pattern" not in task.check:
        raise ValueError(f"{source.name}:{task.id}: regex needs a pattern")
    if not task.question.strip():
        raise ValueError(f"{source.name}:{task.id}: empty question")
