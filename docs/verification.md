# Verification record

What was measured, on what, with which commands, so that every public claim
about cidx can be traced to a reproducible run. Numbers are reported as
measured; where two runs disagreed, both are shown. Update this file when
the claims it backs change.

## Environment

- cidx at the commit named in each section (`git log --oneline -1`).
- Windows 11 Home (10.0.26200), Python 3.13.7, git 2.51.0.windows.1,
  tree-sitter 0.25.2, watchdog 6.0.0, mcp 1.29.0. One laptop; no other
  load during timed runs unless stated.
- Target repository: `django/django` at
  `2b30f6255b5ef84afbd827993643d52ef2c0963a` (2026-09-08, `VERSION =
  (6, 2, 0, "alpha", 0)`), a `--depth 1` clone. Discovery yields
  **3,043 files**, and the index holds **76,166 symbols** and
  **206,801 references** — the same three counts from a source checkout
  and from the published 0.1.0a1 wheel via `uvx`.

## Reproduce

```bash
git clone --depth 1 https://github.com/django/django.git django
cidx index --repo django            # time this
cidx stats --repo django
cidx check --repo django            # expect: no drift
cidx query get_object_or_404 --repo django
cidx query get_object_or_404 --references --repo django
cidx query django/shortcuts.py --outline --repo django
cidx query --repo-map --repo django
python scripts/index_fingerprint.py --repo django
python scripts/mcp_smoke.py --repo django --name Model.save
```

Wall-clock times below were taken around those commands (`cidx index`
also prints its own elapsed time). The phase breakdown and the hot-path
numbers came from timers placed around the same library calls the CLI
makes (`indexer.iter_source_files`, `hashing.content_hash`,
`indexer.extract_source`, `Store.replace_file`, `Store.resolve_references`,
`incremental.refresh_path`).

## Indexing (Django, cidx 7f7686d)

| Path | Measured | Notes |
|---|---|---|
| `cidx index`, empty cache, warm OS file cache | **30.5 s** | 3,043 files; matches the 30.9 s first reported for 0.1.0a1 |
| `cidx index`, empty cache, cold OS file cache | 67.8 s and 97.2 s | first read of a fresh clone; `read+hash` alone was 31.5 s cold vs 0.75 s warm |
| Phase breakdown, warm | discovery 0.4 s · read+hash 0.75 s · parse+extract 8.4 s · SQLite writes 23.5 s · resolution 1.9 s | of 35.1 s in that run |
| `cidx index` again over the populated index | **28.6–49.5 s** (three runs) | before ADR-016: killed at 684 s, unfinished |
| `cidx serve` from an empty cache until every file is present | **123 s** (cidx 3be4297) | real subprocess; before ADR-015: 483 files at 120 s, unfinished at 400 s |
| `cidx check` | 23.7 s, 58.6 s, 58.8 s | a cold rebuild into a temporary database plus a row-set diff; varies with file-cache state |

The two fixes those rows reference: ADR-015 batched whole-index reference
resolution and `git check-ignore` out of the per-file loop of the watcher's
sweep (a doubling test showed 3.8× time per 2× files before it); ADR-016
added indexes on the three foreign-key columns, taking one file's delete
from 361 ms (max 1.0 s) to 1.7 ms, plans from `SCAN` to covering-index
`SEARCH`.

## Hot path: one saved file (Django, cidx 7f7686d)

| Measurement | Result |
|---|---|
| `incremental.refresh_path` on `django/db/models/base.py` (156 symbols), edit then revert | 1.90 s and 1.95 s |
| of which: rows replaced (parse, extract, one transaction) | 0.21–0.26 s |
| of which: whole-index `resolve_references` | 1.4–1.6 s |
| unchanged file (content hash matches) | 28 ms |
| save → queryable through the real watcher, 10 back-to-back saves | p50 **1.77 s**, p95 1.82 s, max 1.84 s; the first, isolated save was 0.33 s |

The 0.33 s first sample is the honest shape of the hot path: the saved
file's own rows are committed first, so its definitions are queryable about
a third of a second after the save; the whole-index re-resolution then runs
for ~1.5 s, and a save arriving during it waits.

Where resolution's time goes, from timers inside `resolve_all` on the full
index: loading definitions and imports 0.28–0.35 s, recomputing 206,801
references in Python 0.70–0.88 s, the UPDATE 0.73–0.77 s. In steady state
zero rows change. A variant that wrote only changed rows was measured and
rejected: rewrite-all 1.42 s (min of 3), Python-side diff 1.75 s, SQL-side
diff 2.45 s — the write is not the bottleneck, the recompute is. The index
had no free-list bloat after three full re-indexes (`freelist_count` 0).

The README's 106 ms save-to-queryable figure was measured on a 500-file
corpus (46k symbols) and does not describe repositories of Django's size.

## Query latency (Django, library path, 60 samples each)

| Query | p50 | p95 | max |
|---|---|---|---|
| `find_definition` (exact) | 16.3 ms | 22.6 ms | 23.8 ms |
| `find_references` | 17.5 ms | 27.0 ms | 27.7 ms |
| `search_symbols` (ranked, fuzzy) | 107.5 ms | 138.8 ms | 196.7 ms |
| `outline_file` | 0.1 ms | 0.3 ms | 1.9 ms |
| `repo_map` | 118.8 ms | 134.7 ms | 154.5 ms |

Exact lookups meet the < 50 ms target at this scale; ranked search and the
repository map do not (both scan: `LIKE '%text%'` over 76k symbols, and a
grouped aggregation over 207k references).

## MCP, end to end

Driven by the official MCP Python client against a real `cidx serve`
subprocess over stdio (the same mechanism as
`tests/integration/test_mcp_server.py`), on the Django index:

- `initialize` succeeds; `tools/list` returns exactly `search_symbols`,
  `find_definition`, `find_references`, `outline_file`, `repo_map`, each
  with an object schema, the documented required argument, and an integer
  `max_tokens`.
- `find_definition("Model.save")` → `django/db/models/base.py:847` with its
  signature; `find_references("get_object_or_404")` → 15 rows tagged
  `[import]` resolved to `django/shortcuts.py`.
- Budget: `find_references("__init__")` → 25 lines, `truncated: true,
  total_matches: 31`, ~720 tokens for a 700 budget; `search_symbols("get",
  max_tokens=100)` → 6 lines, ~115 tokens, `total_matches: 469`.
- A miss on each of `find_definition`, `find_references`,
  `search_symbols`, `outline_file` returns `isError: false` and a message
  recommending grep; `repo_map` on a repository with no code reports the
  index is empty and recommends grep.
- A non-integer `max_tokens` and a missing required argument return
  `isError: true` with a validation message; the server keeps answering.
- `scripts/mcp_smoke.py` passes against `python -m cidx` (source) and
  against `uvx cidx` (published 0.1.0a1).

## Published package, as a stranger (0.1.0a1 via `uvx`, cache redirected)

`uvx cidx --version` → `cidx 0.1.0a1` (58 s on first run, downloading);
`--help` lists `index, query, stats, check, serve`; `index` on Django
51.7 s with the counts above; `check` → `no drift` in 58.8 s; all four
`query` modes and `--json` answer in 0.4 s; the only file written is
`<cache>/cidx/<repo-id>/index.db`; nothing is written inside the
repository. Note that 0.1.0a1 predates ADR-014/015/016: re-indexing and
`serve` on a large repository are slow in that release.

## TypeScript on a real repository (zod, cidx 35899c1)

`colinhacks/zod` at 59bbc03 (511 TypeScript files): `cidx index` → 522
files, 6,211 symbols, 53,535 references in 13.8 s; `cidx check` → no
drift; `cidx query ZodString` → `packages/zod/src/v3/types.ts:731` with
its `extends` clause; references tagged `[exact]`; symbol kinds in the
TypeScript files alone: 71 classes, 779 methods, 1,514 functions, 1,677
consts, 1,921 imports, plus TSX and JavaScript files.

Confidence before and after the emitted-extension fix (a5980d8):
`import` 0 → 853, `exact` 4,185 unchanged, `name-only` 49,350 → 48,497.
The remaining name-only majority is structural: zod imports modules as
namespaces (`import * as core from "./core.js"`) and calls
`core.$constructor(...)`, which binds `core`, not the member, so those
references resolve by unique global name at best. Recorded as a known
limitation in the README.

## Correctness

- Test suite: 263 tests (`pytest -q`), ruff clean, at cidx 35899c1.
- Property suite (`tests/convergence/`): Hypothesis generates up to 12
  random writes, deletes, and renames over eight paths (Python, TypeScript,
  TSX, JavaScript, a non-code file, a junk-directory file) and eight
  contents (empty, broken syntax, unicode, imports), 100 examples per test,
  and asserts the live index's value-level snapshot equals a cold rebuild's
  — refreshed eagerly and as one storm followed by a sweep.
- Crash injection: one test fails before the transaction opens (the index
  is untouched); a second fails inside `replace_file` after the file row and
  symbol rows are inserted and asserts the transaction is closed, the
  snapshot is unchanged, and the next refresh converges.
- Gitignore transitions (a file becoming ignored, or unignored) converge on
  the next sweep, and the per-event path refuses a newly ignored file.
- Snapshots (`Store.snapshot`, used by `cidx check` and the convergence
  suite) are multisets: identical value-rows must match in count. Django
  holds 31 such rows, all in minified vendored JavaScript
  (`select2.full.min.js`, `jquery.min.js`: eleven `function e(e,t,n)` on
  one line), which a set-based comparison would have collapsed.
- A CI failure on `ubuntu-latest / py3.11` at 7f7686d was traced to a
  deferred `BEGIN` in `Store.replace_file`: the watcher's consumer thread
  had read, a test's connection committed schema creation, and the first
  write failed at once with `database is locked` (SQLITE_BUSY_SNAPSHOT
  bypasses the busy timeout). Fixed with `BEGIN IMMEDIATE` (a5ed647) and
  reproduced by `tests/unit/test_store_write_locking.py`; the consumer
  thread is also guarded now, so one failure cannot silently stop
  `cidx serve` (edbbce3).
- `Watcher.stop()` does not drain events still inside the debounce
  window: an edit in the last ~100 ms before shutdown is indexed by the
  next start's sweep (observed once, as a benchmark's final restore of
  `base.py` left one stale symbol until the next `cidx index`).
- `cidx check` on Django reported `no drift` after every path exercised
  here: the cold CLI build, a re-index, the serve-built index, and a
  watcher-maintained index after edits.

## Cross-platform

CI runs lint and the full suite on {Ubuntu, macOS, Windows} × {Python 3.11,
3.12, 3.13} (`.github/workflows/ci.yml`); golden-file extractor tests pin
identical symbol and reference output for the fixture corpus on all three.
For Django-scale evidence, `.github/workflows/cross-platform-django.yml`
indexes the pinned revision on Ubuntu and Windows and fails unless
`scripts/index_fingerprint.py` prints the same SHA-256 of the value-level
snapshot on both; it is a manual (`workflow_dispatch`) workflow. Only the
Windows leg has been run so far, on the machine described above, against a
reconciled index (`cidx check`: no drift):

```
files=3043 symbols=76166 refs=206801 sha256=13defcbd20f4ac9788f7ee5b75d2927e5d872d8ccab6d4eb582594e8af250245
```

A Linux run of the workflow, or of the commands under "Reproduce", at the
same Django revision must print that digest for the "identical on Linux
and Windows" claim to count as verified; until then it is unverified.
