"""
tests/test_parser.py
====================
Unit tests for testgen.parser — acceptance-criteria extraction and chunking.

Tests cover:
  - Happy-path: well-formed numbered list extraction
  - Edge cases: empty input, no numbered items, single item, unicode content
  - Boundary value: exactly 1 item (falls back), exactly 2 items (splits)
  - chunk_items: empty list, single item, exact multiple, remainder batch
  - extract_assumptions: module docstring, no docstring, invalid syntax
"""

import pytest
from testgen.parser import parse_acceptance_items, chunk_items, extract_assumptions


# ---------------------------------------------------------------------------
# parse_acceptance_items — happy path
# ---------------------------------------------------------------------------

class TestParseAcceptanceItemsHappyPath:
    """Tests for well-formed numbered acceptance criteria documents."""

    def test_extracts_preamble_and_two_items(self):
        """Should split a story with preamble + 2 numbered criteria correctly."""
        story = "As a user I want X.\n\n1. The system shall do A.\n2. The system shall do B."
        preamble, items = parse_acceptance_items(story)
        assert "As a user" in preamble
        assert len(items) == 2

    def test_item_text_contains_number_prefix(self):
        """Each item string should include its number prefix."""
        story = "Context\n\n1. First criterion.\n2. Second criterion."
        _, items = parse_acceptance_items(story)
        assert items[0].startswith("1.")
        assert items[1].startswith("2.")

    def test_multiline_item_captured_as_one(self):
        """An item spanning multiple lines should be a single entry."""
        story = "Background\n\n1. This is criterion one\n   which wraps to a second line.\n2. Second criterion."
        _, items = parse_acceptance_items(story)
        assert len(items) == 2
        assert "wraps" in items[0]

    def test_preamble_is_empty_when_no_intro(self):
        """Preamble should be empty string when numbered list starts immediately."""
        story = "1. First.\n2. Second."
        preamble, items = parse_acceptance_items(story)
        assert preamble == ""
        assert len(items) == 2

    def test_thirty_criteria_produces_thirty_items(self):
        """Large document with 30 criteria should produce exactly 30 items."""
        criteria = "\n".join(f"{i}. Criterion number {i}." for i in range(1, 31))
        _, items = parse_acceptance_items("Background text\n\n" + criteria)
        assert len(items) == 30


# ---------------------------------------------------------------------------
# parse_acceptance_items — boundary value analysis
# ---------------------------------------------------------------------------

class TestParseAcceptanceItemsBoundary:
    """Boundary-value tests for the numbered-item threshold."""

    def test_exactly_one_item_returns_empty_list(self):
        """One numbered item should fall back to single-shot (empty items list)."""
        story = "Story\n1. Only one criterion."
        preamble, items = parse_acceptance_items(story)
        assert items == []
        assert preamble == story  # original text returned unchanged

    def test_exactly_two_items_triggers_split(self):
        """Two numbered items is the minimum for batch mode to be viable."""
        story = "1. A.\n2. B."
        _, items = parse_acceptance_items(story)
        assert len(items) == 2


# ---------------------------------------------------------------------------
# parse_acceptance_items — edge cases
# ---------------------------------------------------------------------------

class TestParseAcceptanceItemsEdgeCases:
    """Edge-case tests for unusual input formats."""

    def test_empty_string_returns_empty_items(self):
        """Empty string should return the original as preamble, no items."""
        preamble, items = parse_acceptance_items("")
        assert items == []

    def test_no_numbered_items_returns_whole_text_as_preamble(self):
        """A story without numbering should return the full text as preamble."""
        story = "As a user I want something nice.\nIt should work well."
        preamble, items = parse_acceptance_items(story)
        assert items == []
        assert preamble == story

    def test_unicode_content_handled(self):
        """Unicode characters in criteria should not cause errors."""
        story = "1. 用户应能登录。\n2. 系统应显示欢迎消息。"
        _, items = parse_acceptance_items(story)
        assert len(items) == 2

    def test_indented_numbers_are_recognised(self):
        """Numbers indented with spaces/tabs should still be detected."""
        story = "Intro\n\n  1. Indented criterion A.\n  2. Indented criterion B."
        _, items = parse_acceptance_items(story)
        assert len(items) == 2


# ---------------------------------------------------------------------------
# chunk_items
# ---------------------------------------------------------------------------

class TestChunkItems:
    """Tests for the batch-splitting helper."""

    def test_empty_list_returns_empty(self):
        """Empty input list should produce no chunks."""
        assert chunk_items([], batch_size=8) == []

    def test_single_item_produces_one_batch(self):
        """A single item should produce exactly one batch."""
        result = chunk_items(["only"], batch_size=8)
        assert result == [["only"]]

    def test_exact_multiple_produces_equal_batches(self):
        """16 items with batch_size=8 should produce exactly 2 full batches."""
        items = [str(i) for i in range(16)]
        chunks = chunk_items(items, batch_size=8)
        assert len(chunks) == 2
        assert all(len(c) == 8 for c in chunks)

    def test_remainder_in_final_batch(self):
        """10 items with batch_size=8 should produce 1 full + 1 remainder batch."""
        items = [str(i) for i in range(10)]
        chunks = chunk_items(items, batch_size=8)
        assert len(chunks) == 2
        assert len(chunks[0]) == 8
        assert len(chunks[1]) == 2

    def test_batch_size_one(self):
        """batch_size=1 should produce one batch per item."""
        items = ["a", "b", "c"]
        chunks = chunk_items(items, batch_size=1)
        assert len(chunks) == 3


# ---------------------------------------------------------------------------
# extract_assumptions
# ---------------------------------------------------------------------------

class TestExtractAssumptions:
    """Tests for pulling the ASSUMPTIONS docstring from generated code."""

    def test_returns_module_docstring(self):
        """Should extract the module-level docstring from valid Python code."""
        code = '"""ASSUMPTIONS: login_user(u, p) -> bool"""\nimport pytest\n'
        result = extract_assumptions(code)
        assert "ASSUMPTIONS" in result

    def test_returns_empty_when_no_docstring(self):
        """Code without a module docstring should return an empty string."""
        code = "import pytest\ndef test_foo(): pass\n"
        assert extract_assumptions(code) == ""

    def test_returns_empty_on_syntax_error(self):
        """Invalid Python should not raise — should return empty string."""
        assert extract_assumptions("def (broken syntax:") == ""
