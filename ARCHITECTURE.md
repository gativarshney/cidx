# ARCHITECTURE.md

The technical shape of cidx, condensed and authoritative. If code and this file disagree, fix one of them in the same change.

## System overview

```
                        +---------------------------+
  file saves, git ops   |  watcher (watchdog)       |
  --------------------> |  debounce ~100ms/path     |
                        |  coalesce per path        |
                        +------------+--------------+
                                     |  paths
                                     v
+---------------------+   +---------------------------+
| cold indexer        |   | incremental engine        |
| full walk,          |   | hash check -> parse ->    |
| .gitignore aware    |   | one transaction per file  |
+----------+----------+   +------------+--------------+
           |                           |
           |    rows                   |    rows
           v                           v
        +--------------------------------------+
        | SQLite store (WAL, FTS5)             |
        | files / symbols / refs / meta        |
        | ~/.cache/cidx/<repo-id>/index.db     |
        +-------------------+------------------+
                            |  lookups
                            v
        +--------------------------------------+
        | query layer: rank -> budget -> shape |
        +-------------------+------------------+
                            |
              +-------------+--------------+
              v                            v
        +-----------+              +---------------+
        | CLI       |              | MCP server    |
        | cidx ...  |              | stdio, 5 tools|
        +-----------+              +---------------+

  benchmark/ (in-repo): tasks -> runners -> raw JSONL -> scorer -> league table
```

Two consumers (CLI, MCP) call the same library functions. Neither contains logic of its own.

## Repository layout and component map

```
src/cidx/
  core/         store.py (SQLite), schema.py, hashing.py, indexer.py,
                incremental.py, resolve.py, query.py, watcher.py, repoid.py
  extractors/   base.py, python.py, typescript.py, queries/*.scm
  ranking/      features.py, scorer.py, budget.py
  mcp/          server.py (5 tool definitions, response shaping)
  cli.py        index / query / serve / check / stats
benchmark/
  tasks/        one JSON file per pinned repo (dev + holdout split; ADR-011)
  runners/      agent loop (provider-pluggable model client), stub model, logging
  datasets/     pinned-repo manifests (URL + commit SHA)
  results/      YYYY-MM/ raw JSONL + generated tables
  methodology.md
tests/
  unit/         golden-file extractor tests
  convergence/  property-based suite (the proof of the invariant)
  integration/  real server over stdio
  fixtures/
scripts/        clone_datasets.py, bench helpers, release helpers
docs/           deep-dive.md and future docs
```

## Components

**Parsing (tree-sitter).** `py-tree-sitter` with prebuilt grammar wheels for Python and TypeScript/JavaScript. Chosen because it is error-tolerant (half-written files still parse; broken regions become error nodes) and C-fast. Extraction uses tree-sitter query files (`.scm`) per language, not hand-rolled tree walks, so a new language is mostly data. Files are parsed from bytes; encoding is handled explicitly.

**Symbol extraction.** Emits (name, qualified_name, kind, file, start_line, end_line, signature, parent). Qualified names include parents (`UserRepo.save`). Language edge cases live in the per-language extractor and its golden tests: arrow functions assigned to consts, default exports, re-exports, nested defs, decorators.

**Reference extraction and resolution.** Emits (name, file, line, resolved_symbol_id nullable, confidence). Resolution cascade: same-file scope, then explicit imports followed to their source, then unique global name, else ambiguous with candidates. Confidence tags: `exact`, `import`, `name-only`. There is deliberately no type checker; precision per tier is measured by the benchmark and published rather than promised.

**Store (SQLite).** Stdlib `sqlite3`, WAL mode so the watcher thread writes while the MCP thread reads, `synchronous=NORMAL`, foreign keys on. FTS5 virtual table gives fuzzy symbol search. The index lives outside the repo, keyed by `repo-id` (short hash of the repo root's realpath). Draft schema:

```sql
CREATE TABLE files (
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  language TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  mtime REAL NOT NULL,
  indexed_at REAL NOT NULL
);
CREATE TABLE symbols (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  qualified_name TEXT NOT NULL,
  kind TEXT NOT NULL,             -- function | class | method | const | import
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  signature TEXT,
  parent_id INTEGER REFERENCES symbols(id)
);
CREATE TABLE refs (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  line INTEGER NOT NULL,
  resolved_symbol_id INTEGER REFERENCES symbols(id),
  confidence TEXT NOT NULL        -- exact | import | name-only
);
CREATE VIRTUAL TABLE symbols_fts USING fts5(
  name, qualified_name, signature, content='symbols', content_rowid='id'
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);  -- schema_version, engine_version
CREATE INDEX idx_symbols_name ON symbols(name);
CREATE INDEX idx_refs_name ON refs(name);
CREATE INDEX idx_refs_symbol ON refs(resolved_symbol_id);
```

`ON DELETE CASCADE` makes "remove a file's rows" one statement. `schema_version` in `meta` lets a newer cidx detect an old index and rebuild instead of misreading it.

**Incremental engine.** The heart. Invariant: incremental result equals cold rebuild, always. Per changed path: stat, hash; if hash unchanged, stop (free). Else parse, extract, then a single transaction: delete the file's rows, insert new rows, update the file record. Deletes and renames are the same machinery. Branch switches arrive as event storms: the queue coalesces to one pending entry per path and the hash check discards the untouched majority. Crash mid-update: the transaction rolls back; the index is never half-written. `cidx check` cold-rebuilds into a temp file and diffs row sets against the live index; any drift is printed exactly and doubles as a new convergence test case.

**Watcher.** `watchdog` (inotify / FSEvents / ReadDirectoryChangesW behind one API). Producer thread filters (`.git`, ignore rules, non-code) and debounces ~100ms per path; a consumer thread drains a `queue.Queue` and runs the incremental path. OS watchers drop events under storms, so a periodic reconciliation sweep re-stats and re-hashes everything cheaply as the safety net: fast path for speed, slow path for truth. Threads are fine here despite the GIL because the workload is I/O plus C-level parsing.

**Ranking.** A hand-built weighted linear score over engineered features: match tier (exact > prefix > substring > FTS), symbol kind (definitions over usages over variables), popularity (log-scaled reference count, a one-step PageRank approximation), path locality to recently touched files, edit recency. Weights live in config and are tuned ONLY against the benchmark dev split. No ML, no embeddings: explainable, measurable, zero-dep.

**Token budgeting and response shaping.** Every tool accepts `max_tokens` (default ~700), estimated as chars/4. Responses are terse fixed-shape lines (qualified name, kind, path:line, signature), plus `truncated: true, total_matches: N` when trimmed, an `index_age_ms` freshness stamp, and confidence tags on references. Never return file bodies; return locations and skeletons the agent can verify cheaply. Fail open: on any miss or mid-rebuild query, say so and recommend grep fallback; with cidx installed, the worst case must equal not having it.

**MCP server.** Official Python SDK, stdio transport, spawned by the client, dies with it. Five read-only tools: `search_symbols`, `find_definition`, `find_references`, `outline_file`, `repo_map` (ranked, budgeted overview; Aider's repo-map idea generalized into a queryable tool, credited in docs). Tool descriptions are prompts and get A/B-tested against the benchmark. Read-only is a security stance: a tool that cannot write or execute has no prompt-injection blast radius.

**CLI.** `argparse`, thin dispatcher over the same library calls: `cidx index`, `cidx query`, `cidx serve`, `cidx check`, `cidx stats`, each with `--json`. The CLI must contain no logic of its own, or the CLI and MCP paths drift.

**Benchmark subsystem (`benchmark/`).** Pinned repos (manifest: URL + exact commit) cloned by `scripts/clone_datasets.py`; 30 to 50 tasks with machine-checkable ground truth in JSON (ADR-011), split dev/holdout; contestants as adapters (grep baseline, cidx, Serena, claude-context, codanna, ChunkHound) run by a scripted agent loop with identical model, prompt, and tasks; 3 to 5 repetitions, medians with IQR. Metrics: task success, total tokens, wasted file reads (opened but never cited), wall time, and the headline, cost per solved task. Raw JSONL logs are published; the scorer recomputes every number from logs alone. A stub model (recorded responses) makes development free; paid runs are budget-capped. Full rules: `benchmark/methodology.md`.

## Key data flows

Save path (hot):

```
save -> OS event -> filter -> debounce -> queue
     -> hash (unchanged? stop) -> parse -> extract
     -> ONE transaction (delete old rows, insert new, update file)
     -> queryable again (~100-150ms)
```

Query path:

```
agent question -> model picks a cidx tool -> JSON-RPC over stdio
  -> SQLite lookups -> rank -> trim to token budget
  -> compact response (+freshness, +truncation, +confidence)
  -> agent verifies 1-2 cited files -> answer
```

Benchmark path:

```
task JSON + pinned repos -> runner (per contestant, N reps)
  -> raw JSONL logs -> scorer (recomputes all metrics)
  -> league table -> README + published logs
```

## Testing strategy

Golden-file unit tests per extractor edge case; the property-based convergence suite (hypothesis generates random edit/delete/rename sequences, asserts incremental equals cold rebuild) as the merge-blocking crown jewel; integration tests that spawn the real server and speak MCP over stdio; a branch-switch stress test; a performance regression check against a pinned repo in CI. Target 150 to 250 tests by launch.

## Packaging and CI

Pure-Python wheel; compiled parts arrive via prebuilt tree-sitter wheels, which is what makes Windows first-class. `pyproject.toml` with src layout and a `cidx` entry point; `uv` for dev; PyPI via trusted publishing on tags. CI matrix: {Ubuntu, macOS, Windows} x {3.11, 3.12, 3.13}: ruff, pytest, convergence suite; perf smoke job later. The PyPI name is claimed by the first real 0.1.0a release, preceded by a ten-minute collision search on the final name.
