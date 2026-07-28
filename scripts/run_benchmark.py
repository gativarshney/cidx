"""Drive a benchmark run: tasks x contestants x repetitions, logged as JSONL.

Development runs use the recorded-response stub (--model stub:<recording>);
real provider clients plug in behind the same interface. Results land in
benchmark/results/<label>/ as one raw JSONL log plus a generated league
table, both committed for published runs (methodology.md).

Usage:
  python scripts/run_benchmark.py --label dev-smoke \
      --model stub:recordings.json --contestants grep,cidx --reps 3 \
      [--split dev] [--repos-dir benchmark/datasets/repos]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from benchmark.runners import runner, score  # noqa: E402
from benchmark.runners import tasks as tasks_mod  # noqa: E402
from benchmark.runners.adapters import CidxAdapter, GrepAdapter  # noqa: E402
from benchmark.runners.model import RecordedStub  # noqa: E402

ADAPTERS = {"grep": GrepAdapter, "cidx": CidxAdapter}


def build_model(spec: str):
    kind, _, argument = spec.partition(":")
    if kind == "stub":
        return RecordedStub.from_file(argument)
    raise SystemExit(
        f"unknown model spec {spec!r}; provider clients arrive with the"
        " first paid run (methodology.md caps spend in the run manifest)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="results folder name")
    parser.add_argument("--model", required=True, help="e.g. stub:recording.json")
    parser.add_argument("--contestants", default="grep,cidx")
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    parser.add_argument(
        "--repos-dir",
        type=Path,
        default=REPO_ROOT / "benchmark" / "datasets" / "repos",
    )
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "benchmark" / "results")
    args = parser.parse_args(argv)

    suite = [
        task
        for task in tasks_mod.load_tasks()
        if args.split == "all" or task.split == args.split
    ]
    missing = {
        task.repository
        for task in suite
        if not (args.repos_dir / task.repository).exists()
    }
    if missing:
        raise SystemExit(
            f"pinned repos not materialized: {sorted(missing)};"
            " run scripts/clone_datasets.py first"
        )

    out_dir = args.out / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "raw.jsonl"
    model = build_model(args.model)

    with log_path.open("w", encoding="utf-8") as log:
        for name in args.contestants.split(","):
            adapter_cls = ADAPTERS.get(name.strip())
            if adapter_cls is None:
                raise SystemExit(f"unknown contestant {name!r}")
            by_repo: dict[str, list[tasks_mod.Task]] = {}
            for task in suite:
                by_repo.setdefault(task.repository, []).append(task)
            for repository, repo_tasks in sorted(by_repo.items()):
                adapter = adapter_cls()
                adapter.setup(args.repos_dir / repository)
                try:
                    for task in repo_tasks:
                        for repetition in range(args.reps):
                            if hasattr(model, "start_episode"):
                                model.start_episode(task.id)
                            outcome = runner.run_episode(
                                task,
                                adapter,
                                model,
                                args.repos_dir / repository,
                                log,
                                repetition=repetition,
                            )
                            marker = "ok" if outcome.success else "MISS"
                            print(
                                f"{adapter.name} {task.id} rep{repetition}:"
                                f" {marker} ({outcome.total_tokens} tok)"
                            )
                finally:
                    adapter.teardown()

    episodes = score.rebuild_episodes([log_path])
    table = score.render_table(score.aggregate(episodes))
    (out_dir / "league.md").write_text(table + "\n", encoding="utf-8")
    print()
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
