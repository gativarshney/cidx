"""Provider-pluggable model clients for the scripted agent loop.

A real provider client implements the same two-method surface; development
and CI use the recorded-response stub (methodology.md: build against the
stub, spend money only on real measurements).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: dict


@dataclass(frozen=True, slots=True)
class ModelTurn:
    """One model response: either tool calls or a final answer."""

    tool_calls: tuple[ToolCall, ...] = ()
    answer: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ModelClient(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        """One model turn given the conversation so far and the toolset."""
        ...


@dataclass
class RecordedStub:
    """Deterministic replay of a recorded episode: zero cost, zero variance.

    Recording format (JSON): {"episodes": {"<task-id>": {"turns": [
      {"tool_calls": [{"name": ..., "arguments": {...}}],
       "prompt_tokens": N, "completion_tokens": N},
      {"answer": "...", "prompt_tokens": N, "completion_tokens": N}
    ]}}}
    """

    episodes: dict[str, list[dict]]
    _cursor: dict[str, int] = field(default_factory=dict)
    _active: str | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> RecordedStub:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            episodes={
                task_id: episode["turns"]
                for task_id, episode in document["episodes"].items()
            }
        )

    def start_episode(self, task_id: str) -> None:
        if task_id not in self.episodes:
            raise KeyError(f"no recorded episode for task {task_id!r}")
        self._active = task_id
        self._cursor[task_id] = 0

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        assert self._active is not None, "start_episode() was not called"
        turns = self.episodes[self._active]
        index = self._cursor[self._active]
        if index >= len(turns):
            # a recording that runs dry answers nothing: an honest failure
            return ModelTurn(answer="", prompt_tokens=0, completion_tokens=0)
        self._cursor[self._active] = index + 1
        turn = turns[index]
        return ModelTurn(
            tool_calls=tuple(
                ToolCall(name=c["name"], arguments=c.get("arguments", {}))
                for c in turn.get("tool_calls", [])
            ),
            answer=turn.get("answer"),
            prompt_tokens=int(turn.get("prompt_tokens", 0)),
            completion_tokens=int(turn.get("completion_tokens", 0)),
        )
