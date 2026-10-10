"""find_references says so when nothing it returns actually resolved.

For a method name, a call through an object (``obj.save()``) cannot be tied
to a class without type information, so every such usage comes back as an
unresolved ``[name-only]`` match. On Django, ``find_references("Model.save")``
returned 959 rows and 0 of them resolved to ``Model.save``; the tags were
honest row by row, but nothing told the agent that the whole list was
name-matching. The note does.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cidx.cli import main
from cidx.core import indexer
from cidx.core.store import Store

# Two `save` methods, as in any real codebase. A unique name would resolve
# through the cascade's unique-global-name step, which is a different (and
# already tagged) situation from "nothing resolved".
MODELS = (
    b"class Model:\n    def save(self):\n        return 1\n\n\n"
    b"class Draft:\n    def save(self):\n        return 2\n"
)
VIEWS = b"def handle(obj):\n    obj.save()\n    return obj\n"
DIRECT = b"def helper():\n    return 1\n\n\ndef use():\n    return helper()\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "models.py").write_bytes(MODELS)
    (root / "views.py").write_bytes(VIEWS)
    (root / "direct.py").write_bytes(DIRECT)
    return root


@pytest.fixture
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache = tmp_path / "cache"
    monkeypatch.setenv("LOCALAPPDATA", str(cache))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache


def _mcp_references(repo: Path, db: Path, name: str) -> str:
    from cidx.mcp.server import create_server

    content, _ = asyncio.run(
        create_server(repo, db).call_tool("find_references", {"name": name})
    )
    return content[0].text


class TestMcp:
    def test_all_name_only_results_are_called_out(self, repo, tmp_path) -> None:
        db = tmp_path / "i.db"
        with Store.open(db) as store:
            indexer.index_repository(repo, store)
        text = _mcp_references(repo, db, "Model.save")
        assert "views.py:2  save  [name-only]" in text
        assert "none of these usages resolved to a definition of 'Model.save'" in text

    def test_resolved_results_get_no_note(self, repo, tmp_path) -> None:
        db = tmp_path / "i.db"
        with Store.open(db) as store:
            indexer.index_repository(repo, store)
        text = _mcp_references(repo, db, "helper")
        assert "[exact]" in text
        assert "none of these usages resolved" not in text


class TestCli:
    def test_note_goes_to_stderr(self, repo, isolated_cache, capsys) -> None:
        assert main(["index", "--repo", str(repo)]) == 0
        capsys.readouterr()
        assert main(["query", "Model.save", "--references", "--repo", str(repo)]) == 0
        captured = capsys.readouterr()
        assert "views.py:2" in captured.out
        assert "none of these usages resolved" in captured.err

    def test_resolved_results_print_no_note(self, repo, isolated_cache, capsys) -> None:
        assert main(["index", "--repo", str(repo)]) == 0
        capsys.readouterr()
        assert main(["query", "helper", "--references", "--repo", str(repo)]) == 0
        assert capsys.readouterr().err == ""
