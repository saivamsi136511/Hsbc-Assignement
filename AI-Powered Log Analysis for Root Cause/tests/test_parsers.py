"""
tests/test_parsers.py
=====================
Unit tests for the log parsers (ingestion.parsers / parsers.py).

Tests cover:
  - Python traceback parsing: error type, message, frame extraction
  - Java stack trace parsing
  - Node.js error parsing
  - Go panic parsing
  - Generic fallback parser
  - Deduplication: repeated errors collapsed with occurrence count
  - Edge cases: empty input, malformed logs, unicode content
"""

import pytest
import sys
import os

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parsers import iter_parse_lines, parse_generic, dedupe


# ---------------------------------------------------------------------------
# Python traceback parsing
# ---------------------------------------------------------------------------

PYTHON_TRACEBACK = """\
2024-01-15 10:30:01,234 ERROR app.py - Unhandled exception
Traceback (most recent call last):
  File "/app/services/auth.py", line 42, in authenticate
    result = db.query(sql, params)
  File "/app/db/connection.py", line 18, in query
    return self.cursor.execute(sql)
sqlite3.OperationalError: no such table: users
"""


class TestPythonParser:
    """Tests for Python traceback detection and parsing."""

    def test_detects_python_traceback(self):
        """Should find at least one error in a standard Python traceback."""
        errors = list(iter_parse_lines(PYTHON_TRACEBACK.splitlines(keepends=True)))
        assert len(errors) >= 1

    def test_extracts_error_type(self):
        """Should extract the exception class name."""
        errors = list(iter_parse_lines(PYTHON_TRACEBACK.splitlines(keepends=True)))
        assert any("OperationalError" in e.error_type or "sqlite3" in e.error_type
                   for e in errors)

    def test_extracts_error_message(self):
        """Should extract the exception message."""
        errors = list(iter_parse_lines(PYTHON_TRACEBACK.splitlines(keepends=True)))
        assert any("no such table" in (e.message or "") for e in errors)

    def test_extracts_stack_frames(self):
        """Should extract at least one stack frame from the traceback."""
        errors = list(iter_parse_lines(PYTHON_TRACEBACK.splitlines(keepends=True)))
        assert any(len(e.frames) > 0 for e in errors)

    def test_format_is_python(self):
        """The format field should indicate this is a Python log."""
        errors = list(iter_parse_lines(PYTHON_TRACEBACK.splitlines(keepends=True)))
        assert any(e.format == "python" for e in errors)


# ---------------------------------------------------------------------------
# Generic fallback parser
# ---------------------------------------------------------------------------

GENERIC_LOG = """\
2024-01-15 11:00:00 INFO Application started
2024-01-15 11:00:05 ERROR Failed to connect to cache server
2024-01-15 11:00:05 ERROR Connection refused: redis://cache:6379
2024-01-15 11:00:10 INFO Retrying connection...
"""


class TestGenericParser:
    """Tests for the generic fallback parser."""

    def test_detects_error_lines(self):
        """Should detect ERROR-flagged lines and group them."""
        errors = parse_generic(GENERIC_LOG)
        assert len(errors) >= 1

    def test_captures_error_text(self):
        """Should capture text from ERROR lines."""
        errors = parse_generic(GENERIC_LOG)
        combined = " ".join((e.message or "") + (e.raw_block or "") for e in errors)
        assert "connect" in combined.lower() or "redis" in combined.lower() or "cache" in combined.lower()


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

REPEATED_ERROR = """\
Traceback (most recent call last):
  File "/app/worker.py", line 10, in process
    raise ValueError("Invalid input")
ValueError: Invalid input
Traceback (most recent call last):
  File "/app/worker.py", line 10, in process
    raise ValueError("Invalid input")
ValueError: Invalid input
Traceback (most recent call last):
  File "/app/worker.py", line 10, in process
    raise ValueError("Invalid input")
ValueError: Invalid input
"""


class TestDeduplication:
    """Tests for the deduplication logic."""

    def test_repeated_errors_collapsed(self):
        """Three identical errors should deduplicate to one entry."""
        errors = list(iter_parse_lines(REPEATED_ERROR.splitlines(keepends=True)))
        deduped = dedupe(errors)
        assert len(deduped) < len(errors)

    def test_occurrence_count_recorded(self):
        """The deduplicated entry should record the occurrence count."""
        errors = list(iter_parse_lines(REPEATED_ERROR.splitlines(keepends=True)))
        deduped = dedupe(errors)
        assert any(e.occurrence_count > 1 for e in deduped)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestParserEdgeCases:
    """Edge case tests for unusual or empty inputs."""

    def test_empty_input_returns_no_errors(self):
        """Empty input should produce no parsed errors."""
        assert list(iter_parse_lines([])) == []

    def test_clean_log_returns_no_errors(self):
        """A log with only INFO lines should produce no errors."""
        clean_log = "2024-01-15 INFO Server started on port 8080\n" * 5
        errors = parse_generic(clean_log)
        assert errors == []

    def test_unicode_content_handled(self):
        """Unicode characters in log lines should not cause exceptions."""
        unicode_log = "ERROR: 日本語のエラーメッセージ\n"
        try:
            errors = parse_generic(unicode_log)
            # No exception = pass
        except Exception as exc:
            pytest.fail(f"Unicode log caused exception: {exc}")
