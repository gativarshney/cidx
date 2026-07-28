# MILESTONES.md: Execution Phases

Phase-based, self-paced. One phase is in play at a time; work happens only on the current phase's scope. Phases are ordered by dependency, not by calendar; done means the Definition of Done, whenever that happens.

## Standing rules

- Definition of Done is per phase and does not move. Scope moves instead.
- The convergence suite gates every merge from Phase 4 onward.
- Job applications and interviews always win schedule conflicts; the project pauses cleanly at the last green merge and resumes at the same phase.
- The owner hand-writes the first version of three core modules: the SQLite schema (Phase 3), the invalidation logic (Phase 4), and the ranking feature set (Phase 7). Later contributions extend and test those modules; they do not originate them (ADR-009).

## Phase 1: Project Foundation

- Goal: a repository where every later phase lands through green CI and reviewed pull requests.
- Deliverables: pyproject.toml (src layout, `cidx` entry point); package tree stubs (`core/`, `extractors/`, `ranking/`, `mcp/`, `cli.py`); tests tree with one passing test; CI matrix ({Ubuntu, macOS, Windows} x {3.11, 3.12, 3.13}) running ruff and pytest; CHANGELOG.md, CONTRIBUTING.md, SUPPORT.md, issue templates; branch protection on main; the PR flow exercised once end to end.
- Definition of Done: a trivial PR travels branch to green CI (all nine jobs) to reviewed merge; `pip install -e .` succeeds; `cidx --help` prints on all three OSes.
- Dependencies: none.
- Suggested next phase: Phase 2.

## Phase 2: Parser & Symbol Extraction

- Goal: bytes in, structured symbols and raw references out, for Python and TypeScript/JavaScript.
- Deliverables: py-tree-sitter integration with prebuilt grammar wheels; `.scm` query files per language; extractors emitting symbols (name, qualified_name, kind, lines, signature, parent) and raw references; a fixture corpus covering the edge cases named in ARCHITECTURE.md (arrow functions on consts, default exports, re-exports, nested defs, decorators); 30+ golden-file tests.
- Definition of Done: golden suite green on all three OSes; the documented edge-case list is covered; adding a new fixture requires no engine change.
- Dependencies: Phase 1.
- Suggested next phase: Phase 3.

## Phase 3: Storage Layer

- Goal: durable, transactional, searchable persistence with zero setup.
- Deliverables: schema.py implementing the DDL in ARCHITECTURE.md (owner hand-writes first); store.py (WAL, synchronous=NORMAL, foreign keys on, explicit transactions); FTS5 wiring; repo-id and cache location handling (XDG_CACHE_HOME, LOCALAPPDATA on Windows); schema_version check on open; cold indexer honoring .gitignore and size caps; `cidx index`, basic `cidx query` (exact and FTS lookup), `cidx stats`.
- Definition of Done: cold index of a real 100k-LOC repository completes within the ARCHITECTURE.md target; queries return correct rows; a kill during indexing leaves a consistent database, proven by a test; all three OSes green.
- Dependencies: Phase 2.
- Suggested next phase: Phase 4.

## Phase 4: Incremental Indexing

- Goal: the sacred invariant: incremental result equals cold-rebuild result, always.
- Deliverables: content-hash invalidation (owner hand-writes first); per-file transactional swap (delete old rows, insert new, update file record); delete and rename handling; `cidx check` (cold rebuild into temp, row-set diff, exact drift report); the property-based convergence suite (hypothesis generating random edit, delete, rename, and branch-switch sequences); crash-recovery tests.
- Definition of Done: convergence suite green across thousands of generated sequences on Linux and Windows; `cidx check` reports zero drift after arbitrary manual edits; the suite becomes a required CI check from this phase forward.
- Dependencies: Phase 3.
- Suggested next phase: Phase 5.

## Phase 5: Watcher

- Goal: the index stays fresh without the user ever thinking about it.
- Deliverables: watchdog producer thread and indexer consumer thread meeting at a queue; ~100ms per-path debounce; per-path coalescing; ignore filtering shared with the cold indexer; periodic reconciliation sweep as the dropped-event safety net; branch-switch stress test; measured numbers (p95 save-to-queryable, idle CPU).
- Definition of Done: a branch switch converges in seconds; the stress test is green in CI; measured p95 is recorded in the README; a test that artificially drops events shows the reconciliation sweep catching them.
- Dependencies: Phase 4.
- Suggested next phase: Phase 6.

## Phase 6: Query Engine

- Goal: precise answers, candidly labeled.
- Deliverables: the reference-resolution cascade (same-file scope, then imports followed to source, then unique global name, else ambiguous with candidates) with confidence tags (`exact`, `import`, `name-only`) maintained at index time; definition, references, outline, and repo-map data queries; full `cidx query` with `--json`; query performance measured against the p95 target.
- Definition of Done: on fixture repos, definition lookups are exact; reference precision per confidence tier is measured and recorded; outline and repo-map outputs are stable under test; query p95 meets target.
- Dependencies: Phase 4; benefits from Phase 5 but does not require it.
- Suggested next phase: Phase 7.

## Phase 7: Ranking & Token Budgets

- Goal: the right 20 results when 400 match, sized for an agent's context window.
- Deliverables: the ranking feature set (match tier, symbol kind, log-scaled reference popularity, path locality, edit recency; owner hand-writes first); weighted linear scorer with weights in config; token estimator (chars/4); response shaping (terse fixed-shape lines, truncation marker with total count, index freshness stamp, confidence tags); fail-open messages recommending grep fallback.
- Definition of Done: ranked outputs fit their budgets under test; the shaping contract is unit-tested; a written note in the code records that weights stay untuned until the benchmark dev split exists, so tuning happens against measurement, never vibes.
- Dependencies: Phase 6.
- Suggested next phase: Phase 8.

## Phase 8: MCP Server

- Goal: cidx working inside a real MCP client, end to end.
- Deliverables: stdio server on the official MCP Python SDK; the five read-only tools (`search_symbols`, `find_definition`, `find_references`, `outline_file`, `repo_map`) with prompt-quality descriptions; integration tests that spawn the real server subprocess and speak MCP over stdio; fail-open behavior verified; a recorded demo of an MCP-connected coding agent answering "where is X defined, who uses Y" on a large repo through cidx.
- Definition of Done: registering cidx in an MCP client's configuration works on all three OSes, verified against at least two major clients; the integration suite is green; the demo exists.
- Dependencies: Phase 7 for shaping; Phase 6 as the minimum.
- Suggested next phase: Phase 9.

## Phase 9: Benchmark

- Goal: replace claims with a reproducible league table.
- Deliverables, in order: `benchmark/methodology.md` FIRST (metrics, repetitions, medians with IQR, dev/holdout task split, honesty rules, API cost caps), before any ranking tuning; pinned datasets (manifest with URL and commit SHA, plus `scripts/clone_datasets.py`); 30 to 50 tasks with machine-checkable ground truth, split dev/holdout; runner with a recorded-response stub mode and budget caps; contestant adapters (grep baseline, cidx, and at least two competitors, with more welcome by PR); scorer that recomputes every metric from raw JSONL logs; ranking weights tuned on the dev split only; league table and raw logs committed under `benchmark/results/<YYYY-MM>/`.
- Definition of Done: a published table (task success, tokens per task, wasted reads, wall time, cost per solved task) from 3 to 5 repetitions, including at least one metric cidx does not win reported at equal prominence; a stranger can re-derive every number from the committed logs; the holdout set is untouched by tuning.
- Dependencies: Phase 8.
- Suggested next phase: Phase 10.

## Phase 10: Packaging & Release

- Goal: one-command install for strangers, and a launch that leads with data.
- Deliverables: final name check (a short collision search, per ADR-001) and first PyPI release via trusted publishing; `uvx cidx` verified on all three OSes; README rebuilt around the benchmark table; MCP registry listing plus PulseMCP and Smithery; plugin manifests and directory listings for major MCP clients; npm pointer package directing npx users to uvx; demo GIF; launch posts staged as three drops (methodology, results, engine) plus outreach to authors of standing "best code MCP" comparison posts; support cadence written into SUPPORT.md and calendared.
- Definition of Done: a stranger with no prior context installs in one command and gets a correct answer inside their coding agent; the resume line is updated with measured numbers; both old tutorial-tier projects are deleted from the resume.
- Dependencies: Phase 9.
- Suggested next phase: maintenance rhythm (recurring triage) and deliberate grooming of the deferred list.

## Kill criteria (agreed in advance; not renegotiable mid-phase)

- If the convergence suite is not boringly stable by the end of Phase 4's budgeted effort: cut ranking sophistication in Phase 7 and ship three tools instead of five in Phase 8. Correctness is never the cut.
- If the benchmark shows cidx losing to the grep baseline on task success (not merely tying): do not launch the engine as a recommendation; launch the benchmark as the product with cidx listed as a work-in-progress contestant. That is still a complete, resume-worthy project.
- A pause at any phase boundary is a valid outcome: Phases 1 through 4 alone already produce the artifact that replaces the weak resume projects.

## Deferred list (v2 candidates, rejected for v1 on record)

Third and further languages; embeddings or hybrid retrieval; call graphs and impact analysis; HTTP transport; editor plugins; multi-repo support; write tools; web dashboards; a Rust rewrite.

## Success tiers (graded at the first post-launch review, against promises, not moods)

- Minimum (still a win): green convergence suite on three OSes; published benchmark with baseline plus two or more competitors and raw logs; PyPI package with one-command install; ten or more real strangers tried it; 150+ tests; the owner can whiteboard every component; both tutorial projects deleted from the resume.
- Good: 100+ real users; 150 to 400 stars; benchmark cited by at least one standing comparison post; 25 to 40 percent token reduction at accuracy parity, reproduced by someone else; one outside contributor; the project fills 20+ interview minutes with depth to spare.
- Excellent: 500 to 1,000 stars; the benchmark becomes the reference link in agent-retrieval arguments; a competitor's maintainer engages; a meetup talk; interviewers raise the project before the owner does.
- Dream: placement in a major agent's curated plugin directory; thousands of stars; a vendor adopts the methodology; inbound interest from a developer-tooling company.
