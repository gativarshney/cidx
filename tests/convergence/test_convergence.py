"""The property-based convergence suite: proof of the sacred invariant.

Hypothesis generates random edit/delete/rename sequences over a small pool of
paths and hostile contents (broken syntax, wrong-language bytes, unicode,
empty files). However the sequence lands — refreshed eagerly after every
change, or all at once like a branch-switch storm — the incrementally
maintained index must equal a cold rebuild, row for row.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cidx.core import incremental, indexer
from cidx.core.store import Store

PATHS = (
    "a.py",
    "b.py",
    "pkg/c.py",
    "d.ts",
    "pkg/e.tsx",
    "f.js",
    "notes.txt",
    ".venv/lib/vendored.py",  # junk dir: both paths must treat it as invisible
)
CONTENTS = (
    b"",
    b"def alpha():\n    return beta()\n",
    b"def broken(:\n",
    b"class C:\n    LIMIT = 1\n\n    def m(self):\n        return calc()\n",
    b"export const handler = () => dispatch();\n",
    b"const plain = 1;\n",
    "GR\u00dcSSE = 'hallo'\n".encode(),
    b"import os\nfrom pkg.mod import thing as alias\n",
)

_write = st.tuples(
    st.just("write"),
    st.integers(0, len(PATHS) - 1),
    st.integers(0, len(CONTENTS) - 1),
)
_delete = st.tuples(st.just("delete"), st.integers(0, len(PATHS) - 1))
_rename = st.tuples(
    st.just("rename"),
    st.integers(0, len(PATHS) - 1),
    st.integers(0, len(PATHS) - 1),
)
operation_sequences = st.lists(
    st.one_of(_write, _delete, _rename), min_size=1, max_size=12
)


def apply_operation(root: Path, operation: tuple) -> list[str]:
    """Mutate the working tree; return the relative paths that changed."""
    kind = operation[0]
    if kind == "write":
        _, path_index, content_index = operation
        target = root / PATHS[path_index]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(CONTENTS[content_index])
        return [PATHS[path_index]]
    if kind == "delete":
        _, path_index = operation
        target = root / PATHS[path_index]
        if target.exists():
            target.unlink()
        return [PATHS[path_index]]
    _, source_index, dest_index = operation
    if source_index == dest_index:
        return []
    source = root / PATHS[source_index]
    dest = root / PATHS[dest_index]
    if not source.exists():
        return []
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    source.rename(dest)
    return [PATHS[source_index], PATHS[dest_index]]


def assert_converged(root: Path, live: Store) -> None:
    """The one assertion that matters: live snapshot == cold rebuild snapshot."""
    with tempfile.TemporaryDirectory(prefix="cidx-conv-") as tmp:
        with Store.open(Path(tmp) / "cold.db") as cold:
            indexer.index_repository(root, cold)
            assert live.snapshot() == cold.snapshot()


@settings(max_examples=100, deadline=None)
@given(operations=operation_sequences)
def test_eager_refresh_converges(operations: list[tuple]) -> None:
    """Refreshing after every single change matches a cold rebuild."""
    with (
        tempfile.TemporaryDirectory(prefix="cidx-repo-") as repo_dir,
        tempfile.TemporaryDirectory(prefix="cidx-db-") as db_dir,
    ):
        root = Path(repo_dir)
        with Store.open(Path(db_dir) / "live.db") as live:
            for operation in operations:
                for touched in apply_operation(root, operation):
                    incremental.refresh_path(live, root, touched)
            assert_converged(root, live)


@settings(max_examples=100, deadline=None)
@given(operations=operation_sequences)
def test_storm_then_sweep_converges(operations: list[tuple]) -> None:
    """A branch-switch-shaped storm followed by one coalesced sweep converges."""
    with (
        tempfile.TemporaryDirectory(prefix="cidx-repo-") as repo_dir,
        tempfile.TemporaryDirectory(prefix="cidx-db-") as db_dir,
    ):
        root = Path(repo_dir)
        with Store.open(Path(db_dir) / "live.db") as live:
            for operation in operations:
                apply_operation(root, operation)
            for path in PATHS:  # the queue coalesces to one entry per path
                incremental.refresh_path(live, root, path)
            assert_converged(root, live)


class TestCrashRecovery:
    def test_crash_mid_update_leaves_old_state_and_recovers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        (root / "a.py").write_bytes(b"def one():\n    return 1\n")
        with Store.open(tmp_path / "db" / "live.db") as live:
            incremental.refresh_path(live, root, "a.py")
            before = live.snapshot()
            (root / "a.py").write_bytes(b"def two():\n    return 2\n")

            def exploding(source: bytes, language_id: str) -> None:
                raise RuntimeError("simulated crash mid-update")

            monkeypatch.setattr(indexer, "extract_source", exploding)
            with pytest.raises(RuntimeError):
                incremental.refresh_path(live, root, "a.py")
            assert live.snapshot() == before  # nothing half-written
            monkeypatch.undo()

            incremental.refresh_path(live, root, "a.py")
            assert_converged(root, live)
