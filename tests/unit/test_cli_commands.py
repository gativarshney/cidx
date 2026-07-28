"""End-to-end tests for cidx index / query / stats through main()."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cidx.cli import main


@pytest.fixture
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the index cache at a temp dir so tests never touch the real one."""
    cache = tmp_path / "cidx-cache"
    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", str(cache))
    else:
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_bytes(
        b"class Repo:\n    def save(self):\n        return commit()\n"
    )
    return root


class TestIndexCommand:
    def test_indexes_and_reports(
        self,
        repo: Path,
        isolated_cache: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(["index", "--repo", str(repo)]) == 0
        out = capsys.readouterr().out
        assert "indexed 1 files" in out
        assert str(isolated_cache) in out

    def test_json_output_is_parseable(
        self,
        repo: Path,
        isolated_cache: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(["index", "--repo", str(repo), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["indexed"] == 1
        assert payload["symbols"] == 2
        assert payload["refs"] == 1

    def test_missing_directory_errors_actionably(
        self, isolated_cache: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["index", "--repo", "does/not/exist"]) == 1
        assert "not a directory" in capsys.readouterr().err


class TestQueryCommand:
    def test_exact_lookup_prints_location_lines(
        self,
        repo: Path,
        isolated_cache: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        main(["index", "--repo", str(repo)])
        capsys.readouterr()
        assert main(["query", "save", "--repo", str(repo)]) == 0
        out = capsys.readouterr().out
        assert "Repo.save" in out
        assert "app.py:2" in out

    def test_falls_back_to_fuzzy_search(
        self,
        repo: Path,
        isolated_cache: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        main(["index", "--repo", str(repo)])
        capsys.readouterr()
        assert main(["query", "sav", "--repo", str(repo)]) == 0
        assert "Repo.save" in capsys.readouterr().out

    def test_no_match_recommends_grep(
        self,
        repo: Path,
        isolated_cache: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        main(["index", "--repo", str(repo)])
        capsys.readouterr()
        assert main(["query", "nonexistent_zz", "--repo", str(repo)]) == 0
        assert "grep" in capsys.readouterr().out

    def test_json_output_is_a_list_of_rows(
        self,
        repo: Path,
        isolated_cache: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        main(["index", "--repo", str(repo)])
        capsys.readouterr()
        assert main(["query", "save", "--repo", str(repo), "--json"]) == 0
        rows = json.loads(capsys.readouterr().out)
        assert rows[0]["qualified_name"] == "Repo.save"
        assert rows[0]["start_line"] == 2

    def test_unindexed_repo_errors_with_next_step(
        self,
        repo: Path,
        isolated_cache: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(["query", "save", "--repo", str(repo)]) == 1
        err = capsys.readouterr().err
        assert "cidx index" in err


class TestStatsCommand:
    def test_reports_counts_and_location(
        self,
        repo: Path,
        isolated_cache: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        main(["index", "--repo", str(repo)])
        capsys.readouterr()
        assert main(["stats", "--repo", str(repo), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["files"] == 1
        assert payload["symbols"] == 2


class TestBareInvocation:
    def test_no_subcommand_prints_help_and_exits_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main([]) == 0
        assert "usage: cidx" in capsys.readouterr().out
