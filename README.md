# cidx

[![CI](https://github.com/gativarshney/cidx/actions/workflows/ci.yml/badge.svg)](https://github.com/gativarshney/cidx/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/cidx)](https://pypi.org/project/cidx/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![Python 3.11–3.13](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)

A zero-config local code index for AI coding agents — with an optional, reproducible evaluation harness for anyone who wants to measure retrieval tools themselves.

**Status: v1 feature-complete, building in public. Alpha releases on [PyPI](https://pypi.org/project/cidx/).**

## What this is

Most coding agents find code by grepping and reading files, which works, but on large repositories it burns tokens on files that never end up mattering. cidx parses a repository into a symbol and reference index (tree-sitter, SQLite), keeps it fresh within milliseconds of every save, and serves ranked, token-budgeted answers over MCP: where a symbol is defined, who uses it, what a file contains, what the repo looks like.

Zero-config means exactly that: no API keys, no vector database, no Docker, no cloud, no accounts. One SQLite file, stored outside your repo (`%LOCALAPPDATA%\cidx` on Windows, `~/.cache/cidx` elsewhere). Read-only by design: the five MCP tools can only look things up, so a hostile file in a repo has no blast radius.

## What works today

- **Two languages**: Python and TypeScript/JavaScript (including TSX/JSX), parsed error-tolerantly — half-written files still index.
- **Cold indexing** honoring `.gitignore` via git, plus a fixed skip-list of build and dependency directories (`.venv`, `node_modules`, `build`, `dist`, …) applied even when a repo forgets to gitignore them, with size caps and stale-row reconciliation on every run.
- **Incremental updates**: content-hash invalidation, one SQLite transaction per file, deletes/renames/branch switches converge; a crash can never half-write the index.
- **File watcher** (`cidx serve`): debounced, coalescing, with a periodic reconciliation sweep as the dropped-event safety net.
- **Reference resolution** with confidence tags — `exact` (same file), `import` (followed to source), `name-only` — recomputed deterministically so incremental and cold indexes always agree.
- **Ranking and token budgets**: engineered features (match tier, kind, popularity, locality, recency) under a weighted linear scorer; responses fit ~700 tokens with truncation markers and freshness stamps; misses recommend grep (fail open).
- **Five read-only MCP tools** over stdio: `search_symbols`, `find_definition`, `find_references`, `outline_file`, `repo_map`.
- **Proof of correctness**: a property-based convergence suite (Hypothesis) asserts the incremental index equals a cold rebuild — including resolutions — across random edit/delete/rename storms, plus `cidx check` for users.
- **Optional evaluation harness**: pinned datasets, 32 machine-checkable tasks (dev/holdout split), a scripted agent loop with a recorded-response stub model, and a scorer that recomputes every metric from raw JSONL logs alone. See [benchmark/methodology.md](benchmark/methodology.md).

## Quickstart

```bash
pip install --pre cidx    # alpha release, so pip needs --pre
```

or run it without installing anything:

```bash
uvx cidx --version
```

From source, for contributors:

```bash
git clone https://github.com/gativarshney/cidx
cd cidx
pip install -e ".[dev]"
```

Index and query a repository:

```bash
cidx index --repo path/to/your/repo
cidx query save --repo path/to/your/repo                  # definitions (exact, then fuzzy)
cidx query save --references --repo path/to/your/repo     # usage sites with confidence
cidx query src/app.py --outline --repo path/to/your/repo  # every symbol in one file
cidx query --repo-map --repo path/to/your/repo            # popular files + top symbols
cidx check --repo path/to/your/repo                       # prove the index matches a cold rebuild
cidx stats --repo path/to/your/repo
```

Every command takes `--json` for machine-readable output.

Add cidx to any MCP-capable coding agent (the watcher keeps the index fresh while serving):

```json
{
  "mcpServers": {
    "cidx": { "command": "cidx", "args": ["serve", "--repo", "path/to/your/repo"] }
  }
}
```

## Measured performance

Measured 2026-07-28 on a mid-range Windows 11 laptop (Python 3.13), against a synthetic 104,500-LOC corpus of 500 Python/TypeScript files; CI regression bounds guard these numbers. Per the project rules, numbers are reported as measured, never tuned to look good.

| Metric | Target (ARCHITECTURE.md) | Measured |
|---|---|---|
| Cold index, ~100k LOC | < 60 s | **8.21 s** (46,000 symbols, 23,000 refs) |
| Save to queryable, p95 | < 150 ms | **106 ms** (20 edits, real watcher) |
| Query p95: find_definition | < 50 ms | **6.8 ms** |
| Query p95: find_references | < 50 ms | **7.8 ms** |
| Query p95: fuzzy search (FTS) | < 50 ms | **22.1 ms** |
| Query p95: outline / repo_map | < 50 ms | **5.3 ms / 20.2 ms** |

Test suite: **241 tests** (golden-file extractor tests, the property-based convergence suite, MCP-over-stdio integration tests), green on CI across {Ubuntu, macOS, Windows} × {Python 3.11, 3.12, 3.13}.

## Known limitations (v1, stated on purpose)

- **TypeScript type-level declarations are not indexed**: `interface`, `type`
  aliases, and `enum` have no symbol kind in the v1 schema. Value-level code
  (functions, classes, methods, consts, imports) is fully covered.
- **CommonJS exports are not tracked as bindings** (`module.exports = {...}`);
  `require(...)` calls do appear as references.
- **No semantic or conceptual search** — by design (ADR-007): retrieval works
  on names, references, and file structure, so "where is auth handled?"
  style questions are out of scope for v1.
- **Reference resolution has no type checker.** Confidence tags (`exact`,
  `import`, `name-only`) state how each reference was resolved rather than
  promising precision; the evaluation harness can measure it per tier.
- An index can be momentarily stale between a save and the watcher's update
  (~100 ms) — every response carries an `index_age_ms` freshness stamp, and
  `cidx check` can prove convergence at any time.

## Evaluation harness (optional)

This repository also contains `benchmark/`: a complete, tested harness for measuring agent retrieval across tools (a grep-only baseline, cidx, and competitor adapters welcome by PR) on pinned repositories. It is optional — the project is complete without it. Anyone can run it with their own API credentials via `scripts/run_benchmark.py`, or develop against the free recorded-response stub model. The honesty rules in [benchmark/methodology.md](benchmark/methodology.md) govern any results someone chooses to publish: raw JSONL logs alongside every table, every number recomputable from the logs, and losses shown exactly like wins.

## Project documents

- [ARCHITECTURE.md](ARCHITECTURE.md): how it works, component by component
- [MILESTONES.md](MILESTONES.md): the phase-based execution plan and definitions of done
- [DECISIONS.md](DECISIONS.md): every architectural decision, with reasons, dated
- [benchmark/methodology.md](benchmark/methodology.md): how measurements are made, written before the first run
- [AGENTS.md](AGENTS.md): the engineering working contract for this repo

## Who is building this

I'm Gati Varshney, a Google Summer of Code 2026 contributor.

This project is built in public. The architectural decisions are documented, the implementation is fully open source, performance claims are measured rather than asserted, and an evaluation harness ships with the repository so anyone can verify retrieval quality independently.

## License

Apache-2.0. Benchmark result data additionally CC-BY-4.0.
