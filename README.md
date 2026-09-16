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

Add cidx to any MCP-capable coding agent. `cidx serve` builds the index if none exists and keeps it fresh while serving; use an absolute repository path, with forward slashes on Windows:

```json
{
  "mcpServers": {
    "cidx": { "command": "uvx", "args": ["cidx", "serve", "--repo", "/absolute/path/to/repo"] }
  }
}
```

(or `"command": "cidx", "args": ["serve", "--repo", ...]` when cidx is installed on the PATH). Client setup, what each of the five tools returns, a smoke test, and troubleshooting: [docs/mcp.md](docs/mcp.md).

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

That corpus is small. On Django (3,043 files, 76k symbols, 207k references; measured 2026-09-16 on the same laptop) the shape changes. Every run, and the commands to reproduce it, is in [docs/verification.md](docs/verification.md):

| Metric (Django) | Measured |
|---|---|
| `cidx index`, empty cache | **30.5 s** with a warm file cache; 68–97 s cold |
| `cidx serve` from an empty cache until every file is indexed | **123 s** |
| `cidx index` again over the existing index | 45.6 s (unfinished at 684 s before the foreign-key indexes) |
| Save → definitions queryable, real watcher | **0.33 s** for an isolated save; **1.8 s** p50 back-to-back, because the whole-index re-resolution after each save takes ~1.5 s at this size |
| Query p95: find_definition / find_references | 22.6 ms / 27.0 ms |
| Query p95: search_symbols (ranked) / repo_map | 138.8 ms / 134.7 ms — over the 50 ms target at this scale |
| `cidx check` | 24–59 s, no drift |

Test suite: **260 tests** (golden-file extractor tests, the property-based convergence suite, MCP-over-stdio integration tests), green on CI across {Ubuntu, macOS, Windows} × {Python 3.11, 3.12, 3.13}.

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
- **After a save, freshness costs grow with the repository.** The saved
  file's own rows land in about 0.3 s, but references are then re-resolved
  across the whole index — milliseconds on a small project, about 1.5 s on
  Django — so back-to-back saves queue behind it. Every response carries an
  `index_age_ms` freshness stamp, and `cidx check` can prove convergence at
  any time.
- **Ranked search and the repository map scan.** `search_symbols` and
  `repo_map` take ~135 ms p95 on Django; exact lookups stay under 30 ms.

## Evaluation harness (optional)

This repository also contains `benchmark/`: a complete, tested harness for measuring agent retrieval across tools (a grep-only baseline, cidx, and competitor adapters welcome by PR) on pinned repositories. It is optional — the project is complete without it. Anyone can run it with their own API credentials via `scripts/run_benchmark.py`, or develop against the free recorded-response stub model. The honesty rules in [benchmark/methodology.md](benchmark/methodology.md) govern any results someone chooses to publish: raw JSONL logs alongside every table, every number recomputable from the logs, and losses shown exactly like wins.

## Project documents

- [ARCHITECTURE.md](ARCHITECTURE.md): how it works, component by component
- [MILESTONES.md](MILESTONES.md): the phase-based execution plan and definitions of done
- [DECISIONS.md](DECISIONS.md): every architectural decision, with reasons, dated
- [benchmark/methodology.md](benchmark/methodology.md): how measurements are made, written before the first run
- [AGENTS.md](AGENTS.md): the engineering working contract for this repo
- [docs/mcp.md](docs/mcp.md): connecting an agent, what the five tools return, troubleshooting
- [docs/verification.md](docs/verification.md): every measurement behind the numbers above, with the commands to reproduce them

## Who is building this

I'm Gati Varshney, a Google Summer of Code 2026 contributor.

This project is built in public. The architectural decisions are documented, the implementation is fully open source, performance claims are measured rather than asserted, and an evaluation harness ships with the repository so anyone can verify retrieval quality independently.

## License

Apache-2.0. Benchmark result data additionally CC-BY-4.0.
