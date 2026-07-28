"""Integration tests that spawn the real MCP server and speak stdio.

The server subprocess runs ``python -m cidx serve`` against a temp repo with
its cache redirected into the test's temp dir. Async client code runs via
asyncio.run inside synchronous tests (no plugins needed).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from cidx.cli import main

EXPECTED_TOOLS = {
    "search_symbols",
    "find_definition",
    "find_references",
    "outline_file",
    "repo_map",
}

APP = b"""\
class Repo:
    def save(self):
        return validate()


def validate():
    return True
"""


@pytest.fixture
def cache_env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    cache = tmp_path / "cidx-cache"
    if os.name == "nt":
        env["LOCALAPPDATA"] = str(cache)
    else:
        env["XDG_CACHE_HOME"] = str(cache)
    return env


@pytest.fixture
def repo(tmp_path: Path, cache_env: dict[str, str], monkeypatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_bytes(APP)
    for key in ("LOCALAPPDATA", "XDG_CACHE_HOME"):
        if key in cache_env:
            monkeypatch.setenv(key, cache_env[key])
    assert main(["index", "--repo", str(root)]) == 0  # index before serving
    return root


async def _session_calls(
    repo: Path, env: dict[str, str], calls: list[tuple[str, dict[str, Any]]]
) -> tuple[set[str], list[str]]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "cidx", "serve", "--repo", str(repo)],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            tool_names = {tool.name for tool in listed.tools}
            outputs = []
            for tool_name, arguments in calls:
                result = await session.call_tool(tool_name, arguments)
                outputs.append(result.content[0].text)
            return tool_names, outputs


def test_five_read_only_tools_end_to_end(repo: Path, cache_env: dict[str, str]) -> None:
    tool_names, outputs = asyncio.run(
        _session_calls(
            repo,
            cache_env,
            [
                ("find_definition", {"name": "Repo.save"}),
                ("find_references", {"name": "validate"}),
                ("search_symbols", {"query": "val"}),
                ("outline_file", {"path": "app.py"}),
                ("repo_map", {}),
                ("find_definition", {"name": "does_not_exist_zz"}),
            ],
        )
    )
    assert tool_names == EXPECTED_TOOLS

    definition, references, search, outline, repo_map_out, miss = outputs
    assert "Repo.save" in definition
    assert "app.py:2" in definition
    assert "index_age_ms:" in definition

    assert "app.py:3" in references  # the call site inside save()
    assert "[exact]" in references

    assert "validate" in search

    assert "Repo" in outline
    assert "Repo.save" in outline

    assert "app.py" in repo_map_out
    assert "symbols" in repo_map_out

    # fail-open contract: a miss says so and recommends grep
    assert "grep" in miss
    assert "does_not_exist_zz" in miss
