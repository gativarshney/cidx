---
title: Quickstart
description: Install cidx, index a repository, run your first queries, and connect an MCP client.
---

You need Python 3.11 or newer and git on your PATH.

## Install

```bash
pip install cidx
```

Or run it without installing, using [uv](https://docs.astral.sh/uv/):

```bash
uvx cidx --version
```

## Index a repository

Run this from the repository root:

```bash
cidx index --repo .
```

The index is one SQLite file in your user cache. Nothing is written inside the repository.

## Ask it something

```bash
cidx query Context --repo .
```

```bash
cidx query echo --references --repo .
```

```bash
cidx query src/click/globals.py --outline --repo .
```

```bash
cidx query --repo-map --repo .
```

## Connect your agent

Add cidx to any MCP client that can start a stdio server. Use an absolute path:

```json
{
  "mcpServers": {
    "cidx": {
      "command": "uvx",
      "args": ["cidx", "serve", "--repo", "/absolute/path/to/repo"]
    }
  }
}
```

The full documentation is being written and will replace this page.
