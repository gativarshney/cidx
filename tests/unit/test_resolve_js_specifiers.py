"""Imports whose specifier carries an emitted extension resolve to source.

NodeNext-style TypeScript and ESM JavaScript write ``import { x } from
"./mod.js"`` even when the file on disk is ``mod.ts``. Resolution appended
suffixes to the specifier verbatim (``mod.js.ts``), so the ``import``
confidence tier never fired on such repositories: zod had 0 of 53,535
references resolved through an import, and a plain-JavaScript ``./core.js``
never found ``core.js`` either. The unique global definition still matched,
so these references were tagged ``name-only`` rather than lost.
"""

from __future__ import annotations

from pathlib import Path

from cidx.core import indexer, query, resolve
from cidx.core.store import Store


def test_js_specifier_maps_to_typescript_source_then_the_literal_file() -> None:
    candidates = resolve._js_candidates("./core.js:thing", "src/index.ts")
    assert candidates == [
        ("src/core.ts", "thing"),
        ("src/core.tsx", "thing"),
        ("src/core.js", "thing"),
    ]


def test_import_confidence_fires_through_a_js_specifier(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "core.ts").write_text("export function thing() {\n  return 1;\n}\n")
    (repo / "src" / "index.ts").write_text(
        'import { thing } from "./core.js";\n\nexport const run = () => thing();\n'
    )
    with Store.open(tmp_path / "index.db") as store:
        indexer.index_repository(repo, store)
        refs = [r for r in query.find_references(store, "thing") if r.path == "src/index.ts"]
    assert refs, "the call inside run() must be a reference"
    assert (refs[0].confidence, refs[0].resolved_path) == ("import", "src/core.ts")


def test_plain_javascript_esm_specifier_resolves_to_the_js_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "core.js").write_text("export function thing() {\n  return 1;\n}\n")
    (repo / "index.js").write_text(
        'import { thing } from "./core.js";\n\nexport const run = () => thing();\n'
    )
    with Store.open(tmp_path / "index.db") as store:
        indexer.index_repository(repo, store)
        refs = [r for r in query.find_references(store, "thing") if r.path == "index.js"]
    assert refs
    assert (refs[0].confidence, refs[0].resolved_path) == ("import", "core.js")
