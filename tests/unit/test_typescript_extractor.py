"""Golden-file and behavior tests for the JS/TS/TSX extractor."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from cidx.extractors import base
from cidx.extractors import typescript as tsext

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "typescript"
FIXTURE_PATHS = sorted(
    p for p in FIXTURE_DIR.iterdir() if p.suffix in {".ts", ".tsx", ".js", ".jsx"}
)


def as_document(source: bytes, language_id: str) -> dict[str, Any]:
    extraction = tsext.extract(source, language_id)
    return {
        "symbols": [dataclasses.asdict(s) for s in extraction.symbols],
        "references": [dataclasses.asdict(r) for r in extraction.references],
    }


class TestGolden:
    @pytest.mark.parametrize("path", FIXTURE_PATHS, ids=lambda p: p.name)
    def test_fixture_matches_golden_file(self, path: Path) -> None:
        language_id = base.detect_language(path)
        assert language_id is not None
        golden_path = path.with_suffix(".json")
        expected = json.loads(golden_path.read_text(encoding="utf-8"))
        assert as_document(path.read_bytes(), language_id) == expected, (
            f"extraction drifted from golden file {golden_path.name}; "
            "review the diff, and regenerate the golden only if the new "
            "behavior is intended"
        )

    def test_every_fixture_has_a_golden_file(self) -> None:
        missing = [p.name for p in FIXTURE_PATHS if not p.with_suffix(".json").exists()]
        assert missing == []


class TestSymbolContract:
    def test_unsupported_language_raises_with_guidance(self) -> None:
        with pytest.raises(ValueError, match="unsupported language 'python'"):
            tsext.extract(b"", "python")

    @pytest.mark.parametrize(
        "language_id", [base.JAVASCRIPT, base.TYPESCRIPT, base.TSX]
    )
    def test_empty_source_extracts_nothing(self, language_id: str) -> None:
        extraction = tsext.extract(b"", language_id)
        assert extraction.symbols == ()
        assert extraction.references == ()

    def test_local_const_is_not_a_symbol(self) -> None:
        source = b"function f() {\n  const local = 1;\n  return local;\n}\n"
        names = [s.name for s in tsext.extract(source, base.TYPESCRIPT).symbols]
        assert names == ["f"]

    def test_nested_arrow_is_a_function_symbol(self) -> None:
        source = b"function f() {\n  const helper = () => 1;\n  return helper();\n}\n"
        by_name = {
            s.qualified_name: s for s in tsext.extract(source, base.TYPESCRIPT).symbols
        }
        helper = by_name["f.helper"]
        assert helper.kind == "function"
        assert helper.parent == "f"

    def test_anonymous_default_function_is_named_default(self) -> None:
        source = b"export default function () {\n  return 1;\n}\n"
        (symbol,) = tsext.extract(source, base.TYPESCRIPT).symbols
        assert symbol.name == "default"
        assert symbol.kind == "function"

    def test_named_default_export_is_not_duplicated(self) -> None:
        source = b"export default function main() {\n  return 1;\n}\n"
        symbols = tsext.extract(source, base.TYPESCRIPT).symbols
        assert [s.name for s in symbols] == ["main"]

    def test_field_kinds_split_on_function_values(self) -> None:
        source = b"class C {\n  count = 0;\n  handle = () => 1;\n}\n"
        by_name = {
            s.qualified_name: s for s in tsext.extract(source, base.TYPESCRIPT).symbols
        }
        assert by_name["C.count"].kind == "const"
        assert by_name["C.handle"].kind == "method"

    def test_reexport_star_emits_nothing(self) -> None:
        source = b"export * from './everything';\n"
        extraction = tsext.extract(source, base.TYPESCRIPT)
        assert extraction.symbols == ()
        assert extraction.references == ()


class TestReferenceContract:
    def test_export_default_identifier_is_a_reference(self) -> None:
        source = b"const App = () => 1;\nexport default App;\n"
        refs = tsext.extract(source, base.TYPESCRIPT).references
        assert [(r.name, r.line) for r in refs] == [("App", 2)]

    def test_export_clause_references_local_names(self) -> None:
        source = b"const a = 1;\nconst b = 2;\nexport { a, b as c };\n"
        refs = tsext.extract(source, base.TYPESCRIPT).references
        assert [(r.name, r.line) for r in refs] == [("a", 3), ("b", 3)]

    def test_jsx_lowercase_intrinsics_are_not_referenced(self) -> None:
        source = b"const A = () => <div className={x} />;\n"
        assert tsext.extract(source, base.TSX).references == ()

    def test_jsx_components_are_referenced_in_jsx_files_too(self) -> None:
        source = b"const A = () => <Widget />;\n"
        refs = tsext.extract(source, base.JAVASCRIPT).references
        assert [(r.name, r.line) for r in refs] == [("Widget", 1)]

    def test_bare_identifier_loads_are_not_references(self) -> None:
        source = b"const cb = handler;\n"
        assert tsext.extract(source, base.TYPESCRIPT).references == ()
