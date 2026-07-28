"""Tests for the language registry and tree-sitter parsing foundation."""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

import pytest

from cidx.extractors import base


class TestDetectLanguage:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("app.py", base.PYTHON),
            ("stubs.pyi", base.PYTHON),
            ("index.js", base.JAVASCRIPT),
            ("App.jsx", base.JAVASCRIPT),
            ("mod.mjs", base.JAVASCRIPT),
            ("legacy.cjs", base.JAVASCRIPT),
            ("main.ts", base.TYPESCRIPT),
            ("mod.mts", base.TYPESCRIPT),
            ("legacy.cts", base.TYPESCRIPT),
            ("App.tsx", base.TSX),
        ],
    )
    def test_supported_extensions(self, filename: str, expected: str) -> None:
        assert base.detect_language(filename) == expected

    @pytest.mark.parametrize(
        "filename", ["notes.txt", "README.md", "Makefile", "data.json"]
    )
    def test_unsupported_extensions_return_none(self, filename: str) -> None:
        assert base.detect_language(filename) is None

    def test_extension_case_is_ignored(self) -> None:
        assert base.detect_language("LEGACY.PY") == base.PYTHON

    def test_accepts_path_objects_from_both_path_flavours(self) -> None:
        assert (
            base.detect_language(PureWindowsPath(r"C:\repo\src\app.py")) == base.PYTHON
        )
        assert (
            base.detect_language(PurePosixPath("/repo/src/app.ts")) == base.TYPESCRIPT
        )


class TestGetLanguageAndParser:
    def test_unsupported_language_raises_with_guidance(self) -> None:
        with pytest.raises(ValueError, match="unsupported language 'rust'.*python"):
            base.get_language("rust")

    @pytest.mark.parametrize("language_id", sorted(base.SUPPORTED_LANGUAGES))
    def test_every_supported_grammar_loads(self, language_id: str) -> None:
        assert base.get_language(language_id) is not None

    def test_parser_is_shared_per_language(self) -> None:
        assert base.get_parser(base.PYTHON) is base.get_parser(base.PYTHON)


class TestParse:
    @pytest.mark.parametrize(
        ("language_id", "source", "root_type"),
        [
            (base.PYTHON, b"def f(x: int) -> int:\n    return x\n", "module"),
            (base.JAVASCRIPT, b"const f = (x) => x;\n", "program"),
            (base.JAVASCRIPT, b"const C = () => <div id='x' />;\n", "program"),
            (
                base.TYPESCRIPT,
                b"function f(x: number): number { return x; }\n",
                "program",
            ),
            (base.TSX, b"const C = () => <div id='x' />;\n", "program"),
        ],
    )
    def test_valid_source_parses_clean(
        self, language_id: str, source: bytes, root_type: str
    ) -> None:
        tree = base.parse(source, language_id)
        assert tree.root_node.type == root_type
        assert not tree.root_node.has_error

    def test_broken_python_still_yields_a_tree(self) -> None:
        tree = base.parse(b"def broken(:\n    x =\n", base.PYTHON)
        assert tree.root_node.type == "module"
        assert tree.root_node.has_error

    def test_half_written_typescript_still_yields_a_tree(self) -> None:
        tree = base.parse(b"export function incomplete(a: str", base.TYPESCRIPT)
        assert tree.root_node.type == "program"
        assert tree.root_node.has_error

    def test_empty_source_parses_clean(self) -> None:
        tree = base.parse(b"", base.PYTHON)
        assert tree.root_node.type == "module"
        assert not tree.root_node.has_error

    def test_non_utf8_bytes_do_not_crash(self) -> None:
        tree = base.parse(b"x = 1  # caf\xe9 in latin-1\n", base.PYTHON)
        assert tree.root_node.type == "module"
