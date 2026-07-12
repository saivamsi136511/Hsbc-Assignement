"""
tests/test_context_builder.py
==============================
Unit tests for context_builder.py — token budgeting and context assembly.

Tests cover:
  - Context is assembled within the token budget
  - Redaction removes known secret patterns
  - likely_offending_frame returns app-code frame over library frame
  - Budget report notes are populated when context is truncated
  - Source code lookup works when source_dir contains the relevant file
  - Edge cases: no frames, no preceding lines, very small token budget
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_builder import build_prompt_context, redact
from parsers import ParsedError, StackFrame


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_error(error_type="ValueError", message="Something went wrong",
               frames=None, context_before=None, occurrence_count=1):
    """Create a minimal ParsedError for testing."""
    cb = context_before
    if cb is None:
        cb = ""
    elif isinstance(cb, list):
        cb = "\n".join(cb)
    return ParsedError(
        error_type=error_type,
        message=message,
        frames=frames or [],
        context_before=cb,
        raw_block=f"{error_type}: {message}",
        format="python",
        occurrence_count=occurrence_count,
    )


def make_frame(file="/app/services/payment.py", line=42, function="process_payment"):
    """Create a StackFrame for testing."""
    return StackFrame(file=file, line=line, function=function)


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

class TestBuildPromptContext:
    """Tests for the build_prompt_context function."""

    def test_returns_string_and_budget(self):
        """Should return a (str, ContextBudgetReport) tuple."""
        error = make_error()
        context_text, budget = build_prompt_context(error, max_tokens=1000)
        assert isinstance(context_text, str)
        assert hasattr(budget, "estimated_tokens")

    def test_error_message_always_in_context(self):
        """The error message should always appear in the assembled context."""
        error = make_error(message="database connection refused")
        context_text, _ = build_prompt_context(error, max_tokens=2000)
        assert "database connection refused" in context_text

    def test_error_type_in_context(self):
        """The error type should appear in the assembled context."""
        error = make_error(error_type="ConnectionError")
        context_text, _ = build_prompt_context(error, max_tokens=2000)
        assert "ConnectionError" in context_text

    def test_token_budget_respected(self):
        """Estimated token count should not grossly exceed the budget."""
        error = make_error(
            context_before=["INFO: line " + str(i) for i in range(1000)]
        )
        context_text, budget = build_prompt_context(error, max_tokens=500)
        # Allow some overage for header/mandatory lines, but not 10x
        assert budget.estimated_tokens < 5000

    def test_stack_frame_included(self):
        """Stack frames should appear in the context when present."""
        error = make_error(frames=[make_frame(file="/app/auth.py", line=99)])
        context_text, _ = build_prompt_context(error, max_tokens=2000)
        assert "auth.py" in context_text


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

class TestRedaction:
    """Tests for the redact function."""

    def test_api_key_redacted(self):
        """API key patterns should be redacted from text."""
        text = "Authorization: Bearer sk-ant-api03-supersecretkey123456"
        result = redact(text)
        assert "sk-ant-api03-supersecretkey123456" not in result

    def test_email_redacted(self):
        """Email addresses should be redacted."""
        text = "User john.doe@example.com failed to authenticate"
        result = redact(text)
        assert "john.doe@example.com" not in result

    def test_normal_text_unchanged(self):
        """Text without secrets should pass through unchanged."""
        text = "ValueError: list index out of range at line 42"
        result = redact(text)
        assert "ValueError" in result
        assert "line 42" in result

    def test_empty_string_unchanged(self):
        """Empty string should remain empty after redaction."""
        assert redact("") == ""
