"""Answers must not silently cite files that changed after indexing.

``index_age_ms`` says how long ago the index was written, not whether the
disk has moved on since. With nothing watching (``cidx query`` between
runs, ``serve`` before its first sweep finishes), cidx used to answer with
line numbers from files that had been edited or deleted, and nothing in the
response said so. Observed on Django: a cleaned temp directory left 3 of
7,091 files on disk while queries kept returning full results.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cidx.cli import main
from cidx.core import freshness, indexer
from cidx.core.store import Store
from cidx.ranking import budget

APP = b"class Repo:\n    def save(self):\n        return commit()\n"


@pytest.fixture
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache = tmp_path / "cache"
    monkeypatch.setenv("LOCALAPPDATA", str(cache))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_bytes(APP)
    (root / "other.py").write_bytes(b"def commit():\n    return 1\n")
    return root


class TestChangedPaths:
    def _store(self, tmp_path: Path, repo: Path) -> Store:
        store = Store.open(tmp_path / "index.db")
        indexer.index_repository(repo, store)
        return store

    def test_untouched_files_are_not_reported(self, tmp_path, repo) -> None:
        with self._store(tmp_path, repo) as store:
            assert freshness.changed_paths(store, repo, ["app.py", "other.py"]) == []

    def test_edited_and_deleted_files_are_reported(self, tmp_path, repo) -> None:
        with self._store(tmp_path, repo) as store:
            (repo / "app.py").write_bytes(b"\n\n" + APP)  # every line moved
            (repo / "other.py").unlink()
            assert freshness.changed_paths(store, repo, ["app.py", "other.py"]) == [
                "app.py",
                "other.py",
            ]

    def test_touched_but_identical_file_is_not_reported(self, tmp_path, repo) -> None:
        with self._store(tmp_path, repo) as store:
            stat = (repo / "app.py").stat()
            os.utime(repo / "app.py", (stat.st_atime, stat.st_mtime + 60))
            assert freshness.changed_paths(store, repo, ["app.py"]) == []

    def test_each_path_is_checked_once_in_first_seen_order(
        self, tmp_path, repo
    ) -> None:
        with self._store(tmp_path, repo) as store:
            (repo / "app.py").unlink()
            (repo / "other.py").unlink()
            assert freshness.changed_paths(
                store, repo, ["other.py", "app.py", "other.py"]
            ) == ["other.py", "app.py"]

    def test_stale_message_names_files_and_says_what_to_do(self) -> None:
        message = budget.stale_message(["a.py", "b.py", "c.py", "d.py"])
        assert "4 cited files changed" in message
        assert "a.py, b.py, c.py, +1 more" in message
        assert "cidx index" in message


class TestCliWarnsOnStaleCitations:
    def test_definition_in_a_deleted_file_is_flagged(
        self, repo, isolated_cache, capsys
    ) -> None:
        assert main(["index", "--repo", str(repo)]) == 0
        (repo / "app.py").unlink()
        capsys.readouterr()
        assert main(["query", "Repo.save", "--repo", str(repo)]) == 0
        captured = capsys.readouterr()
        assert "app.py:2" in captured.out  # the index still holds the row
        assert "changed on disk" in captured.err, (
            "a citation into a deleted file must be flagged, not served silently"
        )

    def test_json_output_stays_parseable_when_stale(
        self, repo, isolated_cache, capsys
    ) -> None:
        import json

        assert main(["index", "--repo", str(repo)]) == 0
        (repo / "app.py").write_bytes(b"\n" + APP)
        capsys.readouterr()
        assert main(["query", "Repo.save", "--json", "--repo", str(repo)]) == 0
        captured = capsys.readouterr()
        assert json.loads(captured.out)[0]["path"] == "app.py"
        assert "changed on disk" in captured.err

    def test_fresh_index_prints_no_warning(self, repo, isolated_cache, capsys) -> None:
        assert main(["index", "--repo", str(repo)]) == 0
        capsys.readouterr()
        assert main(["query", "Repo.save", "--repo", str(repo)]) == 0
        assert capsys.readouterr().err == ""


class TestMcpToolsFlagStaleCitations:
    """The server path, called in-process (``create_server`` starts no
    watcher, so nothing races to repair the index under the test)."""

    CALLS = (
        ("search_symbols", {"query": "Repo"}),
        ("find_definition", {"name": "Repo.save"}),
        ("find_references", {"name": "commit"}),
        ("outline_file", {"path": "app.py"}),
        ("repo_map", {}),
    )

    def _answers(self, repo: Path, db: Path) -> dict[str, str]:
        import asyncio

        from cidx.mcp.server import create_server

        server = create_server(repo, db)
        answers = {}
        for tool, arguments in self.CALLS:
            content, _ = asyncio.run(server.call_tool(tool, arguments))
            answers[tool] = content[0].text
        return answers

    def test_every_tool_names_the_changed_file(self, repo, tmp_path) -> None:
        db = tmp_path / "mcp.db"
        with Store.open(db) as store:
            indexer.index_repository(repo, store)
        (repo / "app.py").unlink()
        for tool, text in self._answers(repo, db).items():
            assert "app.py" in text.splitlines()[0] or "app.py" in text, tool
            assert "cited file changed on disk since indexing (app.py)" in text, (
                f"{tool} cited a deleted file without saying so:\n{text}"
            )

    def test_fresh_index_adds_no_note(self, repo, tmp_path) -> None:
        db = tmp_path / "mcp.db"
        with Store.open(db) as store:
            indexer.index_repository(repo, store)
        for tool, text in self._answers(repo, db).items():
            assert "changed on disk" not in text, tool
