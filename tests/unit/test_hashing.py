"""Tests for content hashing."""

from __future__ import annotations

import re

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
