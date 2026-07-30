# Evaluation results

No results are published here, and none are scheduled or promised — the
harness is optional (see DECISIONS.md, ADR-013).

Anyone who runs the harness with their own API credentials and chooses to
publish a run puts it here as `<label>/raw.jsonl` (every model call and tool
call, one JSON line each) plus `<label>/league.md` (the generated table).
Every published number must be recomputable from the raw log alone — see
[../methodology.md](../methodology.md) for the rules, including the
dev/holdout split and the honesty requirements.

Development and CI runs use the recorded-response stub model and are not
results.
