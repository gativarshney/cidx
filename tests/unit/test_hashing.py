"""Tests for content hashing."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cidx.core import hashing


class TestContentHash:
    def test_is_deterministic(self) -> None:
        assert hashing.content_hash(b"data") == hashing.content_hash(b"data")

    def test_differs_for_different_content(self) -> None:
        assert hashing.content_hash(b"one") != hashing.content_hash(b"two")

    def test_empty_input_hashes_cleanly(self) -> None:
        assert re.fullmatch(r"[0-9a-f]{32}", hashing.content_hash(b""))

    def test_format_is_32_lowercase_hex_chars(self) -> None:
        assert re.fullmatch(r"[0-9a-f]{32}", hashing.content_hash(b"x"))


class TestFileHash:
    def test_matches_content_hash_of_file_bytes(self, tmp_path: Path) -> None:
        data = b"def f():\n    return 1\n"
        target = tmp_path / "sample.py"
        target.write_bytes(data)
        assert hashing.file_hash(target) == hashing.content_hash(data)

    def test_streams_content_larger_than_one_chunk(self, tmp_path: Path) -> None:
        data = b"x" * (hashing._CHUNK_SIZE * 2 + 17)
        target = tmp_path / "big.bin"
        target.write_bytes(data)
        assert hashing.file_hash(target) == hashing.content_hash(data)

    def test_missing_file_raises_oserror_for_caller_to_decide(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(FileNotFoundError):
            hashing.file_hash(tmp_path / "vanished.py")
