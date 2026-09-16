# DECISIONS.md

Architecture decision records. Append-only; newest last. Every architectural change, dependency addition, or scope change lands here in the same PR that implements it. Format: context, decision, consequences. Re-arguing a decided entry requires new evidence, not new mood.

---

## ADR-001: Identity and repository structure (2026-07-28, accepted)

Context: solo student maintainer; primary goal is a flagship project visible on a personal profile during a fixed personal hiring window; a two-repo org layout was considered and consciously rejected for v1.
Decision: personal account `gativarshney`, single repository `cidx` containing engine, benchmark (`benchmark/`), docs, and infrastructure. No GitHub organization for now. Product working name `cidx`; final naming call happens before the first PyPI release with a short collision search (cidx verified free on PyPI and npm on 2026-07-28).
Consequences: one CI, one issue tracker, simplest possible onboarding, and every commit lands on the owner's profile. Known trade-off accepted with eyes open: a benchmark hosted inside a contestant's repo has weaker neutrality optics. Mitigations are structural and listed in ADR-005. If the benchmark earns standalone traction or more tools are built, split into a `gati-labs` org later; GitHub transfers preserve stars, issues, and redirects, so the migration cost stays near zero.

## ADR-002: Implementation language is Python (2026-07-28, accepted)

Context: owner is JS-strong, Python-new; AI/GenAI intern screening in India keyword-filters on Python; py-tree-sitter bindings are mature; a Rust competitor (codanna) already owns the maximum-performance niche.
Decision: Python 3.11+ (target 3.12) for engine, benchmark, and tooling. TypeScript rejected (keeps the resume JS-only), Rust rejected (new borrow checker on top of a new domain, and a losing race against codanna on its own terrain).
Consequences: closes the owner's largest stack gap in-flight; C-backed tree-sitter and SQLite keep performance targets reachable; a Rust rewrite is explicitly out of scope for v1.

## ADR-003: Storage is stdlib SQLite, index lives outside the repo (2026-07-28, accepted)

Context: the index must survive restarts, update atomically, stay memory-light, and require zero setup.
Decision: `sqlite3` from the stdlib, WAL mode, FTS5, one transaction per file update; index stored at `~/.cache/cidx/<repo-id>/` (XDG respected, LOCALAPPDATA on Windows), never inside the user's repository.
Consequences: durability and crash safety come from the database, not from custom code; no git pollution; uninstall is deleting one folder. Rejected: JSON files (no atomicity), in-memory state (Serena's 30GB cautionary tale), DuckDB (extra dependency, analytics-shaped), Postgres (a server, thesis-breaking).

## ADR-004: Parsing is tree-sitter; exactly two languages in v1 (2026-07-28, accepted)

Context: extraction must survive half-written code on every save, run at C speed, and cover multiple languages without per-language toolchains.
Decision: py-tree-sitter plus prebuilt grammar wheels; Python and TypeScript/JavaScript only; extraction expressed as .scm query files.
Consequences: error tolerance and incremental parsing for free; Windows stays first-class via wheels; each additional language is deliberately deferred scope, not an implicit promise. Rejected: Python `ast` (single-language, throws on errors), LSP servers (the heavyweight lane), regex (cannot parse nesting).

## ADR-005: Benchmark-first positioning with structural neutrality rules (2026-07-28, accepted)

Context: at the time of this decision, no neutral multi-tool retrieval benchmark exists (the only published evals are one vendor versus grep, and one company testing Serena alone); "another code-index MCP server" is a discounted category (~17k servers); the credible sell per existing evidence is efficiency, not accuracy.
Decision: the benchmark is a first-class product of this repo. cidx is one contestant. Headline metric: cost per solved task, with task success, tokens, wasted reads, and wall time. Neutrality is enforced structurally: raw JSONL logs published with every result, all numbers recomputable from logs, identical conditions for all contestants, losses published at equal prominence, competitor adapters accepted by PR, and a dev/holdout task split with ranking tuned only on dev.
Consequences: the project remains valuable even if cidx loses a metric; the benchmark is the distribution wedge; overfitting to our own test is structurally guarded.

## ADR-006: MCP surface is five read-only tools over stdio (2026-07-28, accepted)

Context: distribution requires speaking the protocol every major agent consumes; repo files can contain hostile text (prompt injection); scope must stay maintainable by one student through interview season.
Decision: official MCP Python SDK, stdio transport, exactly five read-only tools (`search_symbols`, `find_definition`, `find_references`, `outline_file`, `repo_map`). No write or execute tools in v1.
Consequences: zero blast radius by construction and a security story worth telling; the maintained surface stays small; HTTP transport, editing tools, and editor plugins are rejected for v1.

## ADR-007: No embeddings anywhere in v1 (2026-07-28, accepted)

Context: embedding-based competitors require API keys, model downloads, or Docker, which breaks the zero-config thesis; Sourcegraph's Cody walked away from embeddings toward BM25 plus a code graph; Aider thrives with zero embeddings; the accuracy advantage of semantic retrieval remains unproven at parity cost.
Decision: no embeddings, no vector store, no semantic search in v1. Revisit only if our own benchmark shows a decisive quality gap that structural retrieval cannot close.
Consequences: the differentiation ("zero-config, non-embedding, measured") stays intact; conceptual-query recall is a known, stated limitation.

## ADR-008: The convergence invariant is a release gate (2026-07-28, accepted)

Context: a stale or wrong index silently degrades the agent and destroys trust; staleness is the most-cited public objection to code indexes and the stated reason the leading terminal agent ships grep-only retrieval.
Decision: incremental result must equal cold-rebuild result. Enforced by a property-based suite (hypothesis) generating random edit/delete/rename/branch sequences, plus `cidx check` for users, freshness stamps on every response, and fail-open behavior (recommend grep on any miss).
Consequences: the suite blocks merges when red; every user-reported drift becomes a new test case; the staleness objection is answered with a proof artifact, not a claim.

## ADR-009: Review-first solo workflow; core modules are hand-written first (2026-07-28, accepted)

Context: solo maintainer; review quality must not depend on a second person; the owner must be able to defend every architectural decision, in interviews and in public.
Decision: no direct commits to main; all changes land on branches and merge only after the owner reviews the full diff; conventional commits; the SQLite schema, invalidation logic, and ranking features are authored by the owner first, then extended and tested under the same review process as everything else.
Consequences: the PR history becomes a public record of review judgment, and the owner retains deep, defensible ownership of the three modules that carry the core design.

## ADR-010: Licensing (2026-07-28, accepted)

Context: infrastructure norms in 2026 favor permissive licenses with a patent grant; benchmark results should be maximally citable.
Decision: Apache-2.0 for all code; benchmark result data additionally CC-BY-4.0. No CLA; DCO at most, later, if outside contributions grow.
Consequences: company-compatible, contribution-friendly, citation-friendly. Trademark and incorporation questions are explicitly deferred until there is traction worth protecting.

## ADR-011: Benchmark task definitions are JSON, not YAML (2026-07-28, accepted)

Context: ARCHITECTURE.md originally specified benchmark tasks as YAML files. Parsing YAML requires PyYAML, which sits outside the hard dependency cap in AGENTS.md (runtime: tree-sitter + grammar wheels, watchdog, mcp; dev: pytest, hypothesis, ruff) — and that cap requires an ADR plus owner approval before any addition. Benchmark task files are primarily machine-read; YAML's human-readability advantage is marginal for them.
Decision: benchmark task definitions, dataset manifests, and stub recordings are JSON, parsed with the standard library. PyYAML is rejected: no new dependency for benchmark-only tooling, preserving the zero-dependency philosophy that the benchmark harness shares with the engine. ARCHITECTURE.md's task-format references are updated to JSON in the same change.
Consequences: the benchmark tooling runs anywhere Python runs, with nothing to install; task files lose YAML comments (a `comment` field substitutes); competitor adapter authors need only the stdlib to read the suite.

## ADR-012: Publish an alpha to PyPI before Phase 9 completes (2026-07-30, accepted)

Context: the engine is feature-complete for v1 and the package builds cleanly, but the benchmark — the project's differentiating evidence — has no published results yet, and ADR-001 defers the final naming call to just before the first PyPI release. Meanwhile the name `cidx` sits unclaimed on PyPI, and every installation instruction in the README describes a package that does not exist.
Decision: publish `0.1.0a1` to PyPI via trusted publishing (tag-triggered, OIDC, no stored secrets) as a name claim and a working install path (`uvx cidx`, `pip install cidx`). The alpha is explicitly not the launch: no announcement, no benchmark claims, and the README continues to state that results are pending. The Phase 10 launch — README rebuilt around the league table, posts, directory listings — still gates on published benchmark results per MILESTONES.md.
Consequences: the name is secured and the install story becomes testable end to end (including `uvx` on all three OSes) before there is an audience; early strangers can try the tool against the honest "no results yet" framing. Trade-off accepted with eyes open: an alpha is publicly visible before the evidence exists, so anyone who finds it early meets claims of correctness (tested) but not of efficiency (unmeasured) — the version number and changelog say exactly that.

## ADR-013: The benchmark becomes an optional evaluation harness (2026-07-30, accepted)

Context: cidx's priorities changed. The project is an open-source portfolio project demonstrating software engineering, systems design, static analysis, and AI tooling — not a commercial product or a research benchmark. ADR-005 positioned the benchmark as a first-class product and ADR-012 gated the launch on published results; both framings made the repository read as incomplete whenever results were absent, and made release depend on paid model runs.
Decision: benchmarking is removed as a required milestone, release blocker, and success criterion. The entire `benchmark/` implementation, its tests, and its documentation are kept and maintained, described as an optional evaluation harness that anyone can run with their own API credentials. No benchmark results, scheduled evaluations, or future comparisons are promised. The repository is complete and releasable without published results. This partially supersedes ADR-005 (the structural neutrality and honesty rules survive, binding anyone who publishes results from the harness) and ADR-012 (the alpha release stands; the launch no longer waits for results).
Consequences: releases and the project's definition of done depend only on engineering quality — tests, CI, measured engine performance, documentation. The harness remains a demonstration of evaluation-methodology design and a tool others can use; if results are ever published, by the owner or anyone else, the methodology's honesty rules still govern them in full.

## ADR-014: File discovery is gitignore plus a fixed junk-directory skip-list (2026-07-31, accepted)

Context: cold discovery (`iter_source_files`) and the incremental engine's eligibility check (`is_ignored`) used two different definitions of "which files exist". With git available, cold discovery deferred entirely to `git ls-files --exclude-standard`, which lists untracked files inside `.venv`, `node_modules`, `build`, and similar directories whenever a repository fails to gitignore them; the incremental engine's junk-directory list refused those same paths unconditionally. The cold path indexed them and the incremental path deleted them — cold and incremental could not converge, `cidx check` reported drift, and the watcher's first reconciliation sweep triggered it with no user edit at all.
Decision: one shared definition, and exclusion wins. The fixed skip-list of build and dependency directories (renamed `_ALWAYS_IGNORED_DIRS`, since it is no longer a no-git fallback) applies in both discovery modes, layered on top of gitignore semantics. The alternative — making the incremental engine accept whatever git lists — was rejected: it would index thousands of vendored files on any repo that forgets to gitignore its virtualenv, producing a large, slow index full of useless results.
Consequences: repositories that already gitignore these directories see no change (git never listed them). Cold, incremental, and watcher paths now provably agree, restored to the convergence suite's domain by a junk path in its generator pool plus a dedicated regression test. Known trade-off, accepted as the safer default: a repository that deliberately keeps first-party source in a directory named exactly `build`, `dist`, `venv`, or another listed name will not have it indexed.

## ADR-015: The reconciliation sweep batches whole-index work (2026-09-16, accepted)

Context: `cidx serve` builds a missing index through the watcher's first reconciliation sweep, which called `incremental.refresh_path` once per discovered file. `refresh_path` was written for the single-save hot path, so each call did two things that are global rather than local: it recomputed reference resolution over the whole index (`Store.resolve_references`, measured at 1.7 s on Django's 76k symbols / 207k references) and it spawned `git check-ignore` to re-check eligibility (measured at 37 ms per call on Windows). Per file, that made a cold sweep O(n²): the pre-fix implementation had indexed 483 of Django's 3,043 files after 120 s and had not finished at 400 s, and a doubling test (100 → 800 files) showed sweep time growing 3.8× per doubling. The cold CLI path (`indexer.index_repository`) was unaffected: it already resolved once after the walk.
Decision: `refresh_path` gains keyword-only `resolve` and `check_ignored` flags, both defaulting to True so a single-path refresh stays self-contained and immediately queryable. The sweep passes both as False and resolves once in a `finally`, so an early exit on stop can never leave rows whose references were deferred and never resolved. The sweep trusts discovery's own filtering because its paths come from `iter_source_files`, which has already applied gitignore and the junk-directory skip-list (ADR-014); the per-event path keeps `check_ignored=True` because its paths come from raw filesystem events. The alternative — having `serve` run the bulk cold path before starting the watcher — was measured and rejected: the batched sweep and the bulk path build the same rows in the same time (35.0 s vs 35.7 s, warm file cache), and the bulk path would have needed a cancellation hook and a second startup code path while making shutdown block for the whole build.
Consequences: measured on the real implementation (Django at 2b30f62, Windows 11, Python 3.13, warm-to-partial file cache), `cidx serve` from an empty cache populates all 3,043 files in 123 s and `cidx check` then reports no drift. Regression tests assert the work contract rather than wall-clock: a sweep over N files resolves exactly once and runs `is_ignored` zero times, an early-stopped sweep still resolves, and a single-file refresh still resolves on the spot.

## ADR-016: Every foreign-key column is indexed (2026-09-16, accepted)

Context: `files -> symbols` and `files -> refs` cascade on delete, and `symbols.parent_id` references `symbols.id`, but none of those child columns had an index. SQLite enforces a cascade and a parent-side constraint check by looking up the child column, so with the v1 schema every `Store.replace_file` on a populated index planned as `SCAN symbols` / `SCAN refs` / `SCAN symbols`. Measured on Django (3,043 files, 76,166 symbols, 206,801 refs), `_delete_file_rows` cost 361 ms per file (max 1.0 s), and `cidx index` run a second time over its own output was still running after 684 s and was killed, versus 30 s for the fresh build. A fresh build never hit it: an empty index has no rows to delete. Anything that replaces rows in a populated index did: a re-index, a branch switch under the watcher, and every single-file save.
Decision: add `idx_symbols_file`, `idx_symbols_parent`, and `idx_refs_file`, and bump `schema_version` to 2 so an index built by an earlier cidx is rebuilt on first open instead of staying slow. The alternative — dropping `ON DELETE CASCADE` and deleting child rows by hand — was rejected: it needs the same lookups, so the same indexes, and gives up the one-statement removal contract.
Consequences: same run, same machine (Windows 11, Python 3.13, Django at 2b30f62): per-file delete 1.7 ms (207×), re-index over a populated index 45.6 s, `cidx check` reports no drift. The single-save hot path is now bounded by whole-index reference resolution, not by row replacement: rows for a 156-symbol file swap in about 250 ms, then `resolve_references` takes about 3.5 s at this scale. That cost is a consequence of resolving over the whole index after every mutation (ADR-008's convergence guarantee) and is recorded as a known limitation; the published 106 ms save-to-queryable figure was measured on a 500-file corpus and does not describe repositories of this size. Regression tests assert that every foreign-key column leads an index and that the cascade and parent lookups never plan as a scan.
