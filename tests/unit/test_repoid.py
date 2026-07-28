"""Tests for repository identity and cache location handling."""

from __future__ import annotations

import re
from pathlib import Path

from cidx.core import repoid


class TestRepoId:
    def test_is_stable_across_calls(self, tmp_path: Path) -> None:
        assert repoid.repo_id(tmp_path) == repoid.repo_id(tmp_path)

    def test_accepts_str_and_path_equally(self, tmp_path: Path) -> None:
        assert repoid.repo_id(tmp_path) == repoid.repo_id(str(tmp_path))

    def test_equivalent_spellings_of_one_root_agree(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        roundabout = tmp_path / "repo" / ".." / "repo" / "."
        assert repoid.repo_id(repo) == repoid.repo_id(roundabout)

    def test_different_roots_differ(self, tmp_path: Path) -> None:
        first = tmp_path / "a"
        second = tmp_path / "b"
        first.mkdir()
        second.mkdir()
        assert repoid.repo_id(first) != repoid.repo_id(second)

    def test_format_is_short_lowercase_hex(self, tmp_path: Path) -> None:
        assert re.fullmatch(r"[0-9a-f]{16}", repoid.repo_id(tmp_path))


class TestCacheRoot:
    HOME = Path("/home/user")

    def test_windows_uses_localappdata(self) -> None:
        root = repoid._cache_root(
            True, {"LOCALAPPDATA": r"C:\Users\u\AppData\Local"}, self.HOME
        )
        assert root == Path(r"C:\Users\u\AppData\Local") / "cidx"

    def test_windows_falls_back_without_localappdata(self) -> None:
        root = repoid._cache_root(True, {}, Path(r"C:\Users\u"))
        assert root == Path(r"C:\Users\u") / "AppData" / "Local" / "cidx"

    def test_xdg_cache_home_is_respected(self) -> None:
        root = repoid._cache_root(False, {"XDG_CACHE_HOME": "/custom/cache"}, self.HOME)
        assert root == Path("/custom/cache") / "cidx"

    def test_relative_xdg_cache_home_is_ignored_per_spec(self) -> None:
        root = repoid._cache_root(
            False, {"XDG_CACHE_HOME": "relative/cache"}, self.HOME
        )
        assert root == self.HOME / ".cache" / "cidx"

    def test_default_is_dot_cache_under_home(self) -> None:
        assert repoid._cache_root(False, {}, self.HOME) == self.HOME / ".cache" / "cidx"


class TestIndexPath:
    def test_lives_outside_the_repo_and_ends_with_index_db(
        self, tmp_path: Path
    ) -> None:
        path = repoid.index_path(tmp_path)
        assert path.name == "index.db"
        assert path.parent.name == repoid.repo_id(tmp_path)
        assert not path.is_relative_to(tmp_path)
