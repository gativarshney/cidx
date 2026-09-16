"""Files that become gitignored, or stop being, converge on the next sweep.

The property suite covers edits, deletes, renames, and junk directories, but
runs without git, so a change to ``.gitignore`` itself is not in its domain.
A ``.gitignore`` edit produces no code-file event (the engine treats the
path as absent), so it is the reconciliation sweep that must restore the
invariant; the per-event path must at least refuse to re-index the file.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cidx.core import incremental, indexer
from cidx.core.store import Store
from cidx.core.watcher import Watcher

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run([GIT, "init", "--quiet", str(repo)], check=True, capture_output=True)
    (repo / "keep.py").write_text("def keep():\n    pass\n")
    (repo / "toggle.py").write_text("def toggled():\n    pass\n")
    return repo


def test_file_that_becomes_ignored_leaves_the_index_on_sweep(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    watcher = Watcher(repo, tmp_path / "index.db")
    with Store.open(tmp_path / "index.db") as store:
        watcher._sweep(store)
        assert "toggle.py" in store.indexed_paths()
        (repo / ".gitignore").write_text("toggle.py\n")
        watcher._sweep(store)
        assert "toggle.py" not in store.indexed_paths()
        assert store.lookup_exact("toggled") == []
        assert incremental.check_drift(repo, store) == []


def test_file_that_stops_being_ignored_enters_the_index_on_sweep(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)
    (repo / ".gitignore").write_text("toggle.py\n")
    watcher = Watcher(repo, tmp_path / "index.db")
    with Store.open(tmp_path / "index.db") as store:
        watcher._sweep(store)
        assert "toggle.py" not in store.indexed_paths()
        (repo / ".gitignore").write_text("")
        watcher._sweep(store)
        assert "toggle.py" in store.indexed_paths()
        assert incremental.check_drift(repo, store) == []


def test_event_for_a_newly_ignored_path_is_refused_by_the_engine(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)
    with Store.open(tmp_path / "index.db") as store:
        indexer.index_repository(repo, store)
        (repo / ".gitignore").write_text("toggle.py\n")
        assert incremental.refresh_path(store, repo, "toggle.py") == "removed"
        assert incremental.check_drift(repo, store) == []
