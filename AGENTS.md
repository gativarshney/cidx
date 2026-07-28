# AGENTS.md

Read this file at the start of every working session. It is the engineering contract for how cidx gets built, regardless of editor, assistant, or environment.

## Quick facts

- Project: cidx, a zero-config local code index for AI coding agents, plus a neutral retrieval benchmark.
- Owner: Gati Varshney (GitHub: gativarshney). Solo maintainer. Final-year B.Tech CSE (Data Science) student; GSoC 2026 @ OpenPrinting; Winter of Code 5.0 Top 20 Contributor. This is a flagship portfolio project.
- Repo: github.com/gativarshney/cidx (single repo: engine + benchmark + docs).
- Language: Python 3.11+ (target 3.12). Package and CLI name: `cidx`. Install story: `uvx cidx`.
- Index location: outside the repo, at `~/.cache/cidx/<repo-id>/index.db` (XDG_CACHE_HOME respected; %LOCALAPPDATA%\cidx on Windows). Never write index files inside a user's repository.
- Current phase: see MILESTONES.md and work ONLY on the current phase's scope.

## What cidx is, in two sentences

cidx parses a repository into a symbol and reference index with tree-sitter, keeps it fresh in real time via a file watcher, and serves ranked, token-budgeted answers to coding agents over MCP. The repo also contains `benchmark/`, a reproducible harness that measures agent retrieval quality and cost across tools, with cidx as one contestant among several.

## Hard constraints (v1 scope law)

These are decisions, not suggestions. Do not "improve" past them.

1. Exactly two languages indexed in v1: Python and TypeScript/JavaScript.
2. Exactly five MCP tools, all read-only: `search_symbols`, `find_definition`, `find_references`, `outline_file`, `repo_map`.
3. Zero-config forever: no API keys, no Docker requirement, no embeddings, no vector DB, no cloud calls, no accounts. `sqlite3` from the stdlib is the only database.
4. Read-only by design: cidx never writes to, executes, or modifies a user's repository. No write tools, ever, in v1.
5. Transport is MCP over stdio using the official Python SDK. No HTTP server in v1.
6. Runtime dependencies are capped at: `tree-sitter` (py-tree-sitter), tree-sitter language grammar wheels (Python, TS/JS), `watchdog`, `mcp`. Dev-only: `pytest`, `hypothesis`, `ruff`. Adding ANY other dependency requires an ADR in DECISIONS.md and owner approval first.

## The invariant (sacred)

The incremental index must always equal what a cold rebuild would produce. Edits, deletes, renames, and branch switches must converge, and crashes must never corrupt (every file update is one SQLite transaction). The property-based convergence suite in `tests/convergence/` is the proof. A red convergence suite blocks every merge, no exceptions, and correctness is never traded for speed or features.

## Do-not-build list

Rejected with reasons on record (see DECISIONS.md and docs/ARCHITECTURE.md). Do not implement, scaffold, or "leave hooks for": embeddings or semantic search, editing/refactoring tools, third and further languages, call graphs and blast-radius analysis, HTTP transport, editor plugins or VS Code extensions, multi-repo support, web dashboards, LSP integration. If asked for any of these, point to this list.

## Performance targets (publish what we measure)

- Cold index: a 100k-LOC repo in seconds (target under 60s worst case on a mid laptop).
- Hot path: p95 under 150ms from file save to queryable.
- Query: p95 under 50ms.
- Responses: fit the per-tool token budget (default ~700 tokens, estimated as chars/4); always include a truncation marker with total match count, an index freshness stamp, and file:line evidence. References carry confidence tags (exact / import-resolved / name-only).
- Never hand-tune numbers to look good. If a target is missed, the README reports the measured number.

## How we work (the workflow contract)

- Never commit to `main`. All work happens on branches (`feat/…`, `fix/…`, `chore/…`, `bench/…`, `docs/…`) and lands via pull request. The owner reads every diff before merging; write PRs that are reviewable (small, one concern each).
- Conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `bench:`, `chore:`). User-visible changes update CHANGELOG.md.
- The owner authors the first version of three core modules: the SQLite schema, the incremental invalidation logic, and the ranking feature set, because they carry the project's core design decisions. Later contributions extend and test those modules; they do not replace the owner's design. Everything else follows the normal cycle: draft, review, revise, merge.
- Every behavior change ships with tests in the same PR. Test layers: golden-file tests for extractors (`tests/unit/`), property-based convergence tests (`tests/convergence/`), MCP-over-stdio integration tests (`tests/integration/`), fixtures in `tests/fixtures/`.
- CI (3 OSes x Python 3.11/3.12/3.13) must be green before merge. Windows is first-class; never use POSIX-only paths or APIs without a fallback.
- Run `pytest -q` before proposing any merge. Start each session by reading the current phase in MILESTONES.md and running the test suite to learn the actual state.
- Any architectural change, new dependency, or scope change gets a dated entry in DECISIONS.md in the same PR.

## Code style

- Type hints everywhere; `ruff` clean (lint + format). No clever metaprogramming, no premature abstraction, no speculative generality. Prefer boring stdlib solutions.
- Public functions get docstrings that state contract, not narration. Error messages must tell the user what to do next.
- SQLite discipline: WAL mode, `synchronous=NORMAL`, `foreign_keys=ON`, all multi-row mutations inside explicit transactions, schema_version checked on open.
- MCP tool descriptions are prompts: wording changes agent behavior, so treat them as a measured surface (A/B against the benchmark, note results).

## Benchmark rules (summary; benchmark/methodology.md governs)

- The benchmark must remain credible despite living in cidx's repo: raw JSONL logs are published with every result, every number is recomputable from logs alone, all contestants run the same tasks under the same conditions, losses are published at the same prominence as wins, and competitor contestants are accepted by PR.
- Tasks are split into a dev set and a holdout set. Ranking may be tuned ONLY against the dev set; holdout results are reported untouched. Never tune anything against holdout tasks.
- Paid API runs are budget-capped; develop the harness against the recorded-response stub model, spend money only on real measurements.

## When uncertain

Prefer the smaller scope. Ask the owner rather than assuming. If a decision is made mid-session, write it into DECISIONS.md immediately. The project's thesis is that a small, provably correct, candidly measured tool beats a large vague one; every choice should serve that sentence.
