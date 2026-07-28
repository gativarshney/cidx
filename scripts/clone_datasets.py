"""Materialize the pinned benchmark repositories.

Reads benchmark/datasets/manifest.json and clones each repository at its
pinned commit into benchmark/datasets/repos/<name> (gitignored). Re-running
is idempotent: an existing checkout at the right commit is left alone.

Usage: python scripts/clone_datasets.py [--manifest PATH] [--dest PATH]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "benchmark" / "datasets" / "manifest.json"
DEFAULT_DEST = REPO_ROOT / "benchmark" / "datasets" / "repos"


@dataclass(frozen=True, slots=True)
class PinnedRepo:
    name: str
    url: str
    commit: str


def load_manifest(path: Path) -> list[PinnedRepo]:
    """Parse and validate the manifest; raises ValueError on bad entries."""
    document = json.loads(path.read_text(encoding="utf-8"))
    repos = []
    for entry in document["repositories"]:
        commit = entry["commit"]
        if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
            raise ValueError(
                f"{entry['name']}: commit must be a full 40-char SHA, got {commit!r}"
            )
        repos.append(PinnedRepo(name=entry["name"], url=entry["url"], commit=commit))
    return repos


def current_commit(checkout: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=checkout,
            capture_output=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.decode("ascii", errors="replace").strip()


def materialize(repo: PinnedRepo, dest_dir: Path) -> str:
    """Clone or fast-path one pinned repo; returns what happened."""
    checkout = dest_dir / repo.name
    if checkout.exists():
        if current_commit(checkout) == repo.commit:
            return "up-to-date"
        subprocess.run(
            ["git", "fetch", "origin", repo.commit],
            cwd=checkout,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-c", "advice.detachedHead=false", "checkout", repo.commit],
            cwd=checkout,
            check=True,
            capture_output=True,
        )
        return "updated"
    dest_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--quiet", repo.url, str(checkout)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "advice.detachedHead=false", "checkout", repo.commit],
        cwd=checkout,
        check=True,
        capture_output=True,
    )
    return "cloned"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args(argv)
    for repo in load_manifest(args.manifest):
        outcome = materialize(repo, args.dest)
        print(f"{repo.name}: {outcome} @ {repo.commit[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
