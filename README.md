# cidx

A zero-config local code index for AI coding agents, and a neutral benchmark for measuring what code-retrieval tools actually save you.

**Status: pre-alpha, building in public.**

## What this is

Most coding agents find code by grepping and reading files, which works, but on large repositories it burns tokens on files that never end up mattering. cidx parses a repository into a symbol and reference index (tree-sitter, SQLite), keeps it fresh within milliseconds of every save, and serves ranked, token-budgeted answers over MCP: where a symbol is defined, who uses it, what a file contains, what the repo looks like.

Zero-config means exactly that: no API keys, no vector database, no Docker, no cloud, no accounts. One SQLite file, stored outside your repo. Read-only by design.

This repository also contains `benchmark/`: a reproducible harness that measures agent retrieval across tools (a grep-only baseline, cidx, and existing alternatives) on pinned repositories with published raw logs. cidx is a contestant, not the referee's favorite: losses get published at the same size as wins, and competitor adapters are welcome by PR.

## Planned quickstart (not live yet)

Add cidx to any MCP-capable coding agent's server configuration:

```json
{
  "mcpServers": {
    "cidx": { "command": "uvx", "args": ["cidx", "serve"] }
  }
}
```

## Project documents

- [ARCHITECTURE.md](ARCHITECTURE.md): how it works, component by component
- [MILESTONES.md](MILESTONES.md): the phase-based execution plan and definitions of done
- [DECISIONS.md](DECISIONS.md): every architectural decision, with reasons, dated
- benchmark/methodology.md: how measurements are made; written before the first benchmark run, in the Benchmark phase
- [AGENTS.md](AGENTS.md): the engineering working contract for this repo

## Who is building this

I'm Gati Varshney, a final-year B.Tech CSE (Data Science) student, GSoC 2026 contributor at OpenPrinting, and Winter of Code 5.0 Top 20 Contributor. This project is built in public, under a workflow where every change lands by pull request and the core modules (schema, invalidation, ranking) are written by hand first. The decision log is in the open; the benchmark exists so that claims here are measurements, not adjectives.

## License

Apache-2.0. Benchmark result data additionally CC-BY-4.0.
