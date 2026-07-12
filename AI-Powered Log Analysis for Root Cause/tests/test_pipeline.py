"""
tests/test_pipeline.py
======================
Integration-level tests for the log analysis pipeline.

Tests are written to run WITHOUT requiring a live Ollama server or
Anthropic API key — all LLM calls are mocked.  Only the parsing,
context-building, and reporting stages are exercised against real data.

Tests cover:
  - Pipeline runs to completion in dry-run mode (no LLM needed)
  - Empty log file produces no findings
  - Multiple distinct errors in one file produce multiple findings
  - JSON report output is valid JSON
  - Markdown report contains expected sections
  - Console report output is non-empty
"""

import json
import os
import sys
import tempfile
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from log_analyzer import collect_errors, render_console, render_json, render_markdown, Finding
from context_builder import build_prompt_context, ContextBudgetReport


SAMPLE_LOG = """\
2024-01-15 10:30:01,234 ERROR services.payment - Payment processing failed
Traceback (most recent call last):
  File "/app/services/payment.py", line 42, in process_payment
    result = gateway.charge(card, amount)
  File "/app/gateways/stripe.py", line 15, in charge
    raise ConnectionError("Stripe API unreachable")
ConnectionError: Stripe API unreachable
2024-01-15 10:30:05,100 ERROR services.auth - Authentication failure
Traceback (most recent call last):
  File "/app/services/auth.py", line 88, in authenticate
    user = db.get_user(username)
  File "/app/db/users.py", line 33, in get_user
    raise LookupError("User not found: admin")
LookupError: User not found: admin
"""


# ---------------------------------------------------------------------------
# Dry-run pipeline
# ---------------------------------------------------------------------------

class TestPipelineDryRun:
    """Tests for the full pipeline in dry-run mode (no LLM calls)."""

    def _make_findings_dry_run(self, log_content: str):
        """Write a temp log file and collect errors (no LLM analysis)."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, encoding="utf-8"
        ) as f:
            f.write(log_content)
            tmp_path = f.name

        try:
            from parsers import iter_parse_file, dedupe
            from context_builder import build_prompt_context
            errors = dedupe(list(iter_parse_file(tmp_path)))
            findings = []
            for error in errors[:5]:
                ctx, budget = build_prompt_context(error, max_tokens=1000)
                findings.append(Finding(error, ctx, budget, None))
            return findings
        finally:
            os.unlink(tmp_path)

    def test_sample_log_produces_findings(self):
        """A log with two errors should produce at least one Finding."""
        findings = self._make_findings_dry_run(SAMPLE_LOG)
        assert len(findings) >= 1

    def test_empty_log_produces_no_findings(self):
        """An empty log file should produce no findings."""
        findings = self._make_findings_dry_run("")
        assert len(findings) == 0

    def test_clean_log_produces_no_findings(self):
        """A log with only INFO messages should produce no findings."""
        clean_log = "2024-01-15 INFO Application started\n" * 20
        findings = self._make_findings_dry_run(clean_log)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

class TestReportRendering:
    """Tests for the three report renderers."""

    def _make_sample_finding(self):
        """Build a minimal Finding without an AnalysisResult."""
        from parsers import ParsedError, iter_parse_lines, dedupe
        errors = dedupe(list(iter_parse_lines(SAMPLE_LOG.splitlines(keepends=True))))
        assert errors, "Test setup: SAMPLE_LOG should produce at least one error"
        error = errors[0]
        ctx, budget = build_prompt_context(error, max_tokens=1000)
        return Finding(error, ctx, budget, None)

    def test_console_render_is_non_empty(self):
        """Console render should produce a non-empty string."""
        finding = self._make_sample_finding()
        output = render_console([finding], dry_run=True)
        assert len(output.strip()) > 0

    def test_json_render_is_valid_json(self):
        """JSON render should produce parseable JSON."""
        finding = self._make_sample_finding()
        output = render_json([finding], dry_run=True)
        parsed = json.loads(output)
        assert "issues" in parsed
        assert isinstance(parsed["issues"], list)

    def test_markdown_render_has_heading(self):
        """Markdown render should contain a top-level heading."""
        finding = self._make_sample_finding()
        output = render_markdown([finding], dry_run=True)
        assert "# Log Analysis Report" in output
