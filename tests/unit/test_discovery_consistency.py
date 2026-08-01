"""Regression: junk directories that git does not ignore must be invisible
to BOTH discovery paths, or cold and incremental disagree and the
convergence invariant breaks."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cidx.core import incremental, indexer
from cidx.core.store import Store

GIT = shutil.which("git")

JUNK = (".venv/lib/a.py", "node_modules/pkg/b.js", "build/c.py")

pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")


def _git_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    _git_repo(root)
    (root / "app.py").write_text("def real():\n    pass\n")
    for rel in JUNK:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def junk():\n    pass\n")
    # deliberately NO .gitignore: git lists these as untracked-not-ignored
    subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "init"], cwd=root, check=True, capture_output=True
    )
    return root


def test_git_discovery_skips_junk_dirs(repo: Path) -> None:
    """Cold discovery must not yield junk dirs even when git lists them."""
    found = {p.relative_to(repo).as_posix() for p in indexer.iter_source_files(repo)}
    assert found == {"app.py"}


def test_cold_and_incremental_agree_on_junk_dirs(tmp_path: Path, repo: Path) -> None:
    """The convergence invariant holds for un-gitignored junk directories."""
    with Store.open(tmp_path / "db" / "live.db") as store:
        indexer.index_repository(repo, store)
        for rel in JUNK:
            incremental.refresh_path(store, repo, rel)
        assert incremental.check_drift(repo, store) == []
