"""CLI smoke tests for the Phase 1 entry point."""

from __future__ import annotations

from importlib.metadata import version

import pytest

from cidx.cli import main


def test_help_exits_zero_and_names_the_tool(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: cidx")
    assert "--version" in out


def test_version_exits_zero_and_prints_package_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"cidx {version('cidx')}"
