# Changelog

All notable changes to cidx are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once the first release exists. Until then, everything lands under Unreleased.

## [Unreleased]

### Fixed

- `cidx index` now reconciles: rows for files that were deleted, renamed,
  newly gitignored, or grew past the size cap are removed on reindex instead
  of lingering (previously `cidx query` served them while `cidx check`
  correctly reported drift).
- The incremental engine refuses paths that discovery would exclude
  (gitignored files, junk directories), so a watcher event can never index
  what a cold rebuild would not.
- Pinned `tree-sitter < 0.26` (heap corruption under repeated queries) and
  `mcp < 2` (2.0.0 breaks FastMCP stdio servers at initialize).

### Added

- Benchmark harness: pinned dataset manifest with `scripts/clone_datasets.py`,
  32 machine-checkable tasks in JSON (dev/holdout split), a scripted agent
  loop with a recorded-response stub model, contestant adapters (grep
  baseline, cidx), and a scorer that recomputes every metric from raw JSONL
  logs alone. Governed by `benchmark/methodology.md`. No results published
  yet.
- MCP server (`cidx serve`): five read-only tools over stdio —
  `search_symbols`, `find_definition`, `find_references`, `outline_file`,
  `repo_map` — with budgeted responses, freshness stamps, and fail-open
  behavior; the file watcher keeps the index fresh while serving.
- Ranking and token budgeting: engineered features (match tier, kind,
  popularity, locality, recency) under a weighted linear scorer with untuned
  default weights; responses fit a ~700-token budget with truncation markers,
  freshness stamps, and fail-open grep recommendations.
- Query engine: reference resolution (same-file, import-following, unique
  global name) with confidence tags; `cidx query` gains `--references`,
  `--outline`, and `--repo-map` modes; `cidx check` verifies the index
  against a cold rebuild and reports drift exactly.
- File watcher: debounced, coalescing, git-aware incremental updates with a
  reconciliation sweep safety net.
- Storage layer: SQLite index (WAL, FTS5) with one-transaction-per-file
  updates, stored outside the repository under the per-user cache directory.
- `cidx index`, `cidx query`, and `cidx stats` commands, each with `--json`.
  Indexing honors `.gitignore` (via git) and skips oversized files.
- TypeScript/JavaScript/TSX symbol and reference extractor: functions
  (including arrow functions bound to consts), classes, methods, class
  fields, consts, imports, re-exports, and anonymous default exports;
  references from calls, `new`, decorators, heritage clauses, and uppercase
  JSX component usages.
- Python symbol and reference extractor: functions, classes, methods, consts,
  and imports with qualified names, one-line signatures, and 1-based line
  spans; raw references from call sites, decorators, and base classes.
  Extraction patterns live in a `.scm` query file shipped with the package.
- Tree-sitter parsing foundation: language detection for Python, JavaScript,
  TypeScript, and TSX files, plus error-tolerant parsing from bytes. First
  runtime dependencies: `tree-sitter` and the three grammar wheels.
- Installable package skeleton (src layout) with the `cidx` console entry point;
  `cidx --help` and `cidx --version` work after `pip install -e .`.
- CI matrix running ruff and pytest on {Ubuntu, macOS, Windows} x {Python 3.11, 3.12, 3.13}.
- Project documentation: README, ARCHITECTURE, DECISIONS, MILESTONES, AGENTS.
- Apache-2.0 license.
