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
