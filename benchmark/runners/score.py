"""Recompute every published number from the raw JSONL logs alone.

The honesty contract (methodology.md): the scorer's only inputs are the log
lines and the committed task definitions (needed to re-run the machine
check). Nothing is taken on trust from the runner's own summaries — tokens
are re-summed from model records, wasted reads re-derived from tool records,
success re-checked from the recorded answer.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path

from benchmark.runners import tasks as tasks_mod


@dataclass(frozen=True, slots=True)
class Episode:
    """One (task, contestant, repetition) rebuilt from primitive log lines."""

    task_id: str
    contestant: str
    repetition: int
    success: bool
    total_tokens: int
    wasted_reads: int
    wall_seconds: float


@dataclass(frozen=True, slots=True)
class ContestantStats:
    contestant: str
    episodes: int
    success_rate: float
    tokens_median: float
    tokens_iqr: tuple[float, float]
    wasted_reads_median: float
    wall_median: float
    cost_per_solved: float | None  # None when nothing was solved


def rebuild_episodes(
    log_paths: list[Path],
    task_index: dict[str, tasks_mod.Task] | None = None,
) -> list[Episode]:
    """Group primitive log lines into episodes and re-derive every metric."""
    if task_index is None:
        task_index = {task.id: task for task in tasks_mod.load_tasks()}
    grouped: dict[tuple[str, str, int], list[dict]] = {}
    for path in log_paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            key = (entry["task"], entry["contestant"], entry["rep"])
            grouped.setdefault(key, []).append(entry)

    episodes = []
    for (task_id, contestant, repetition), entries in sorted(grouped.items()):
        model_entries = [e for e in entries if e["kind"] == "model"]
        tool_entries = [e for e in entries if e["kind"] == "tool"]
        results = [e for e in entries if e["kind"] == "result"]
        answer = results[-1]["answer"] if results else ""
        failure = results[-1].get("failure") if results else "no-result"
        task = task_index.get(task_id)
        success = (
            task is not None
            and failure is None
            and tasks_mod.check_answer(task, answer)
        )
        files_read = {
            str(e["arguments"].get("path", ""))
            for e in tool_entries
            if e["name"] == "read_file"
        }
        cited = {p for p in files_read if p and p in answer}
        timestamps = [e["ts"] for e in entries]
        episodes.append(
            Episode(
                task_id=task_id,
                contestant=contestant,
                repetition=repetition,
                success=success,
                total_tokens=sum(
                    e["prompt_tokens"] + e["completion_tokens"] for e in model_entries
                ),
                wasted_reads=len(files_read - cited),
                wall_seconds=round(max(timestamps) - min(timestamps), 3)
                if timestamps
                else 0.0,
            )
        )
    return episodes


def aggregate(
    episodes: list[Episode],
    price_per_million_tokens: float = 0.0,
) -> list[ContestantStats]:
    """League-table rows, worst headline metric last broken by name."""
    stats: list[ContestantStats] = []
    for contestant in sorted({e.contestant for e in episodes}):
        mine = [e for e in episodes if e.contestant == contestant]
        tokens = [float(e.total_tokens) for e in mine]
        solved = sum(1 for e in mine if e.success)
        total_cost = (
            sum(e.total_tokens for e in mine) / 1_000_000 * (price_per_million_tokens)
        )
        stats.append(
            ContestantStats(
                contestant=contestant,
                episodes=len(mine),
                success_rate=round(solved / len(mine), 4),
                tokens_median=statistics.median(tokens),
                tokens_iqr=_iqr(tokens),
                wasted_reads_median=statistics.median(
                    [float(e.wasted_reads) for e in mine]
                ),
                wall_median=statistics.median([e.wall_seconds for e in mine]),
                cost_per_solved=round(total_cost / solved, 6) if solved else None,
            )
        )
    stats.sort(key=lambda s: (-s.success_rate, s.tokens_median, s.contestant))
    return stats


def render_table(stats: list[ContestantStats]) -> str:
    """The league table, as markdown; losses shown exactly like wins."""
    lines = [
        "| contestant | episodes | success | tokens median (IQR) |"
        " wasted reads | wall s | cost/solved |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in stats:
        low, high = s.tokens_iqr
        cost = f"{s.cost_per_solved:.6f}" if s.cost_per_solved is not None else "-"
        lines.append(
            f"| {s.contestant} | {s.episodes} | {s.success_rate:.0%}"
            f" | {s.tokens_median:.0f} ({low:.0f}-{high:.0f})"
            f" | {s.wasted_reads_median:.1f} | {s.wall_median:.2f} | {cost} |"
        )
    return "\n".join(lines)


def _iqr(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        value = values[0] if values else 0.0
        return (value, value)
    quartiles = statistics.quantiles(values, n=4, method="inclusive")
    return (round(quartiles[0], 3), round(quartiles[2], 3))
