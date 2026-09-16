"""Smoke-test a cidx MCP server exactly the way a client uses it.

Spawns ``cidx serve`` as a subprocess, speaks MCP over stdio with the
official client SDK, checks that exactly the five read-only tools are
registered, and calls ``find_definition`` once. Exit status 0 means an MCP
client will see the same thing.

Usage::

    python scripts/mcp_smoke.py --repo /absolute/path/to/repo
    python scripts/mcp_smoke.py --repo . --command "uvx cidx"
    python scripts/mcp_smoke.py --repo . --name Model.save
"""

from __future__ import annotations

import argparse
import asyncio
import shlex
import sys
from pathlib import Path

EXPECTED_TOOLS = frozenset(
    {"search_symbols", "find_definition", "find_references", "outline_file", "repo_map"}
)


async def probe(command: list[str], repo: Path, name: str) -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=command[0], args=[*command[1:], "serve", "--repo", str(repo)]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            print(f"initialized: server {info.serverInfo.name}")
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            print(f"tools: {', '.join(sorted(names))}")
            if names != EXPECTED_TOOLS:
                print(f"FAIL: expected exactly {sorted(EXPECTED_TOOLS)}")
                return 1
            result = await session.call_tool("find_definition", {"name": name})
            text = result.content[0].text if result.content else ""
            print(f"find_definition({name!r}):")
            for line in text.splitlines():
                print(f"  {line}")
    print("OK: five read-only tools registered and answering")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=".", help="repository root (default: .)")
    parser.add_argument(
        "--command",
        default="cidx",
        help='how to start cidx: "cidx" (default), "uvx cidx", "python -m cidx"',
    )
    parser.add_argument(
        "--name", default="main", help="symbol to look up (default: main)"
    )
    args = parser.parse_args(argv)
    return asyncio.run(
        probe(shlex.split(args.command), Path(args.repo).resolve(), args.name)
    )


if __name__ == "__main__":
    sys.exit(main())
