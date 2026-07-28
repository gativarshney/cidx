"""Tests for the dataset manifest and the pinned-clone machinery.

Cloning is exercised against a local file:// repository, never the network.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GIT = shutil.which("git")


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "clone_datasets", REPO_ROOT / "scripts" / "clone_datasets.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["clone_datasets"] = module
    spec.loader.exec_module(module)
    return module


clone_datasets = _load_module()


class TestManifest:
    def test_committed_manifest_is_valid(self) -> None:
        repos = clone_datasets.load_manifest(clone_datasets.DEFAULT_MANIFEST)
        names = [r.name for r in repos]
        assert len(repos) >= 3
        assert len(set(names)) == len(names)  # unique names
        for repo in repos:
            assert repo.url.startswith("https://")
            assert len(repo.commit) == 40

    def test_short_sha_is_rejected(self, tmp_path: Path) -> None:
        bad = tmp_path / "manifest.json"
        bad.write_text(
            '{"repositories": [{"name": "x", "url": "https://e.com/x",'
            ' "commit": "abc123"}]}',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="full 40-char SHA"):
            clone_datasets.load_manifest(bad)


@pytest.mark.skipif(GIT is None, reason="git not on PATH")
class TestMaterialize:
    @pytest.fixture
    def origin(self, tmp_path: Path) -> tuple[str, str]:
        """A local origin repo; returns (url, pinned first-commit sha)."""
        source = tmp_path / "origin"
        source.mkdir()
        run = lambda *cmd: subprocess.run(  # noqa: E731
            ["git", *cmd], cwd=source, check=True, capture_output=True
        )
        run("init", "--quiet")
        run("config", "user.email", "bench@example.invalid")
        run("config", "user.name", "Bench")
        (source / "lib.py").write_text("def pinned():\n    return 1\n")
        run("add", ".")
        run("commit", "--quiet", "-m", "pinned state")
        pinned = (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=source,
                capture_output=True,
                check=True,
            )
            .stdout.decode()
            .strip()
        )
        (source / "lib.py").write_text("def newer():\n    return 2\n")
        run("commit", "--quiet", "-am", "newer state")
        return source.as_uri(), pinned

    def test_clone_checks_out_the_pinned_commit(
        self, origin: tuple[str, str], tmp_path: Path
    ) -> None:
        url, pinned = origin
        repo = clone_datasets.PinnedRepo(name="local", url=url, commit=pinned)
        dest = tmp_path / "repos"
        assert clone_datasets.materialize(repo, dest) == "cloned"
        assert clone_datasets.current_commit(dest / "local") == pinned
        assert "pinned" in (dest / "local" / "lib.py").read_text()

    def test_rerun_is_idempotent(self, origin: tuple[str, str], tmp_path: Path) -> None:
        url, pinned = origin
        repo = clone_datasets.PinnedRepo(name="local", url=url, commit=pinned)
        dest = tmp_path / "repos"
        clone_datasets.materialize(repo, dest)
        assert clone_datasets.materialize(repo, dest) == "up-to-date"
