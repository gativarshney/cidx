"""The scripted agent loop: one episode per (task, contestant, repetition).

Identical conditions for every contestant: same system prompt, same common
tools (read_file, final_answer), same step and token caps; only the
retrieval toolset differs. Every model call and tool call lands in the raw
JSONL log — the scorer recomputes all published numbers from that log alone
(methodology.md).
"""

from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from benchmark.runners import tasks as tasks_mod
from benchmark.runners.adapters import ToolSpec
from benchmark.runners.model import ModelClient

SYSTEM_PROMPT = (
    "You are a code-navigation agent. Answer the user's question about the"
    " repository using the tools provided. Cite evidence as repo-relative"
    " path:line. When confident, call final_answer with a short answer."
)

_MAX_READ_LINES = 200


@dataclass(frozen=True, slots=True)
class Caps:
    """Hard limits; exceeding either fails the task, recorded as such."""

    max_steps: int = 12
    max_tokens: int = 60_000


@dataclass(frozen=True, slots=True)
class EpisodeResult:
    task_id: str
    contestant: str
    repetition: int
    success: bool
    total_tokens: int
    wasted_reads: int
    wall_seconds: float
    answer: str
    failure: str | None = None  # step-cap / token-cap / none


def common_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="read_file",
            description="Read a repo-relative file (optionally a line range).",
            parameters={
                "path": "repo-relative path",
                "start_line": "first line (optional)",
                "end_line": "last line (optional)",
            },
        ),
        ToolSpec(
            name="final_answer",
            description="End the episode with your answer.",
            parameters={"text": "the answer, citing path:line evidence"},
        ),
    ]


def run_episode(
    task: tasks_mod.Task,
    adapter,
    model: ModelClient,
    repo_root: Path,
    log: TextIO,
    repetition: int = 0,
    caps: Caps | None = None,
) -> EpisodeResult:
    """Run one task with one contestant; returns the checked result."""
    caps = caps if caps is not None else Caps()
    started = time.time()
    toolset = [dataclasses.asdict(t) for t in (adapter.tools() + common_tools())]
    adapter_tool_names = {t.name for t in adapter.tools()}
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task.question},
    ]
    total_tokens = 0
    files_read: set[str] = set()
    answer = ""
    failure: str | None = None

    for step in range(caps.max_steps):
        turn = model.complete(messages, toolset)
        total_tokens += turn.prompt_tokens + turn.completion_tokens
        _log(
            log,
            task,
            adapter.name,
            repetition,
            step,
            "model",
            {
                "tool_calls": [c.name for c in turn.tool_calls],
                "answered": turn.answer is not None,
                "prompt_tokens": turn.prompt_tokens,
                "completion_tokens": turn.completion_tokens,
            },
        )
        if total_tokens > caps.max_tokens:
            failure = "token-cap"
            break
        if turn.answer is not None:
            answer = turn.answer
            break
        if not turn.tool_calls:
            failure = "no-action"
            break
        for call in turn.tool_calls:
            if call.name == "final_answer":
                answer = str(call.arguments.get("text", ""))
                break
            if call.name == "read_file":
                result = _read_file(repo_root, call.arguments)
                files_read.add(str(call.arguments.get("path", "")))
            elif call.name in adapter_tool_names:
                result = adapter.call(call.name, call.arguments)
            else:
                result = f"unknown tool {call.name!r}"
            _log(
                log,
                task,
                adapter.name,
                repetition,
                step,
                "tool",
                {
                    "name": call.name,
                    "arguments": call.arguments,
                    "result_chars": len(result),
                },
            )
            messages.append({"role": "tool", "name": call.name, "content": result})
        if answer:
            break
    else:
        failure = "step-cap"

    success = failure is None and tasks_mod.check_answer(task, answer)
    cited = {path for path in files_read if path and path in answer}
    result = EpisodeResult(
        task_id=task.id,
        contestant=adapter.name,
        repetition=repetition,
        success=success,
        total_tokens=total_tokens,
        wasted_reads=len(files_read - cited),
        wall_seconds=round(time.time() - started, 3),
        answer=answer,
        failure=failure,
    )
    _log(log, task, adapter.name, repetition, -1, "result", dataclasses.asdict(result))
    return result


def _read_file(repo_root: Path, arguments: dict) -> str:
    relative = str(arguments.get("path", ""))
    target = repo_root / relative
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        return f"cannot read {relative!r}: {error}"
    start = int(arguments.get("start_line", 1))
    end = int(arguments.get("end_line", start + _MAX_READ_LINES - 1))
    end = min(end, start + _MAX_READ_LINES - 1)
    window = lines[start - 1 : end]
    return "\n".join(
        f"{number}: {text}" for number, text in enumerate(window, start=start)
    )


def _log(
    log: TextIO,
    task: tasks_mod.Task,
    contestant: str,
    repetition: int,
    step: int,
    kind: str,
    payload: dict,
) -> None:
    log.write(
        json.dumps(
            {
                "ts": round(time.time(), 3),
                "task": task.id,
                "contestant": contestant,
                "rep": repetition,
                "step": step,
                "kind": kind,
                **payload,
            }
        )
        + "\n"
    )
