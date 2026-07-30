# Evaluation methodology

The harness in this directory is optional (ADR-013): running it is
self-funded — bring your own API credentials — and the project is complete
without published results. No evaluations are scheduled or promised.

This document governs any measurement someone chooses to publish from this
harness. It was written before the first run and before any ranking tuning,
on purpose: the rules must exist before there are numbers to be tempted by.
Changes to this document require a dated entry in DECISIONS.md and must never
be applied retroactively to already-published results.

## What is being measured

The cost of answering real code-navigation questions with an AI coding
agent, across retrieval tools. Contestants are retrieval backends an agent
can use — a grep-only baseline, cidx, and competitor tools — run under
identical conditions. cidx is one contestant, not the referee's favorite
(ADR-005): losses are published at the same prominence as wins.

## Metrics

Per task and contestant:

- **Task success** — the machine-checkable ground truth was produced
  (binary; the check lives in the task file, not in a judge's opinion).
- **Total tokens** — prompt plus completion tokens across the whole episode.
- **Wasted reads** — files the agent opened but never cited in its answer.
- **Wall time** — episode start to answer, seconds.
- **Cost per solved task** (headline) — total spend across the run divided
  by the number of solved tasks.

Aggregation: 3 to 5 repetitions per task; medians with interquartile ranges.
Means are never reported alone. No metric is dropped from a published table
because a contestant scores badly on it.

## Tasks

- 30 to 50 tasks against pinned public repositories, each with
  machine-checkable ground truth in JSON (expected file:line spans, symbol
  names, or answer regexes — never free-text judged by a model). JSON keeps
  the benchmark tooling dependency-free (owner decision, 2026-07-28).
- Task shapes: where is X defined; who uses Y; what does file Z contain;
  which module implements behavior W.
- **Dev/holdout split**: tasks are split once, before any tuning. Ranking
  weights and tool descriptions may be tuned ONLY against the dev split.
  Holdout results are reported exactly as first measured. Nothing is ever
  tuned against the holdout split; a violated holdout is discarded and
  rebuilt from new tasks, with the incident recorded in DECISIONS.md.

## Datasets

Pinned repositories: a manifest records URL and exact commit SHA;
`scripts/clone_datasets.py` clones and checks out those SHAs. Every
contestant sees the same bytes. Repos are chosen for size and language mix
(Python and TypeScript/JavaScript, matching cidx's v1 scope) — including
repos large enough that grep-only retrieval is genuinely expensive.

## Conditions

- Identical model, system prompt, task prompt, temperature, and step budget
  for every contestant on every task. The only variable is the retrieval
  tool exposed to the agent.
- Contestants are adapters implementing one interface; competitor adapters
  are accepted by pull request and run unmodified (ADR-005).
- The agent loop is scripted (provider-pluggable model client): no human in
  the loop during a measured episode.
- Episodes have a hard step cap and a hard token cap; exceeding either is a
  failed task, recorded as such.

## Honesty rules

1. **Raw JSONL logs are published with every result.** One line per model
   call and tool call, with timestamps, token counts, and outputs.
2. **Every published number is recomputable from the logs alone.** The
   scorer takes only the JSONL as input; a stranger must be able to re-derive
   the entire league table.
3. Losses are published at the same size and prominence as wins.
4. Failed runs are not silently rerun; every repetition lands in the logs.
5. Measured numbers are never hand-adjusted. If a target is missed, the
   README reports the measured number (AGENTS.md).

## Cost control

- Development runs use a **recorded-response stub model**: real provider
  responses recorded once, replayed deterministically at zero cost. The
  harness is built and debugged entirely against the stub.
- Paid API runs are budget-capped in advance: each real run declares its cap
  in the run manifest before it starts, and the runner halts at the cap. A
  halted run is published as halted, never trimmed to look complete.

## Results layout

`benchmark/results/<YYYY-MM>/` holds the raw JSONL logs and the generated
league table for each published run. Tables state the model, date, dataset
SHAs, and contestant versions used.
