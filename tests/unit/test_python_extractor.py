"""Golden-file and behavior tests for the Python extractor."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from cidx.extractors import python as pyext

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "python"
FIXTURE_STEMS = sorted(p.stem for p in FIXTURE_DIR.glob("*.py"))


def as_document(source: bytes) -> dict[str, Any]:
    extraction = pyext.extract(source)
    return {
        "symbols": [dataclasses.asdict(s) for s in extraction.symbols],
        "references": [dataclasses.asdict(r) for r in extraction.references],
    }


class TestGolden:
    @pytest.mark.parametrize("stem", FIXTURE_STEMS)
    def test_fixture_matches_golden_file(self, stem: str) -> None:
        source = (FIXTURE_DIR / f"{stem}.py").read_bytes()
        golden_path = FIXTURE_DIR / f"{stem}.json"
        expected = json.loads(golden_path.read_text(encoding="utf-8"))
        assert as_document(source) == expected, (
            f"extraction drifted from golden file {golden_path.name}; "
            "review the diff, and regenerate the golden only if the new "
            "behavior is intended"
        )

    def test_every_fixture_has_a_golden_file(self) -> None:
        missing = [
            stem
            for stem in FIXTURE_STEMS
            if not (FIXTURE_DIR / f"{stem}.json").exists()
        ]
        assert missing == []


class TestSymbolContract:
    def test_empty_source_extracts_nothing(self) -> None:
        extraction = pyext.extract(b"")
        assert extraction.symbols == ()
        assert extraction.references == ()

    def test_locals_are_not_symbols(self) -> None:
        source = b"def f():\n    local_var = 1\n    return local_var\n"
        names = [s.name for s in pyext.extract(source).symbols]
        assert names == ["f"]

    def test_function_scoped_imports_are_not_symbols(self) -> None:
        source = b"def f():\n    import json\n    return json\n"
        names = [s.name for s in pyext.extract(source).symbols]
        assert names == ["f"]

    def test_reassigned_const_keeps_first_binding_only(self) -> None:
        source = b"X = 1\nX = 2\n"
        consts = [s for s in pyext.extract(source).symbols if s.kind == "const"]
        assert [(c.name, c.start_line) for c in consts] == [("X", 1)]

    def test_multiline_signature_collapses_to_one_line(self) -> None:
        source = b"def multi(\n    a: int,\n    b: str,\n) -> None: ...\n"
        (symbol,) = pyext.extract(source).symbols
        assert symbol.signature == "def multi( a: int, b: str, ) -> None"
        assert symbol.start_line == 1
        assert symbol.end_line == 4

    def test_method_nested_function_is_a_function_with_method_parent(self) -> None:
        source = (
            b"class C:\n    def m(self):\n        def helper():\n            pass\n"
        )
        by_name = {s.qualified_name: s for s in pyext.extract(source).symbols}
        assert by_name["C.m"].kind == "method"
        helper = by_name["C.m.helper"]
        assert helper.kind == "function"
        assert helper.parent == "C.m"

    def test_wildcard_import_binds_no_symbol(self) -> None:
        source = b"from typing import *\n"
        assert pyext.extract(source).symbols == ()


class TestReferenceContract:
    def test_bare_identifier_loads_are_not_references(self) -> None:
        source = b"def f(cb):\n    return cb\n"
        assert pyext.extract(source).references == ()

    def test_same_name_called_twice_on_one_line_dedupes(self) -> None:
        source = b"y = f(f(1))\n"
        refs = pyext.extract(source).references
        assert [(r.name, r.line) for r in refs] == [("f", 1)]

    def test_chained_calls_reference_each_link(self) -> None:
        source = b"x = a.b().c()\n"
        refs = pyext.extract(source).references
        assert [(r.name, r.line) for r in refs] == [("b", 1), ("c", 1)]
