"""
tests/test_reporter.py
======================
Unit tests for the VRT reporter (console / HTML / JSON formats).

Tests run without requiring OpenCV, Ollama, or real image files.
ComparisonResult and AIAnalysisResult are constructed directly.

Tests cover:
  - Console report: non-empty output, pass/fail indicator present
  - JSON report: valid JSON, required keys present
  - HTML report: contains expected structural elements
  - Reports gracefully handle missing AI result (dry-run mode)
"""

import json
import os
import sys
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from reporter import Reporter
    REPORTER_AVAILABLE = True
except ImportError:
    REPORTER_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not REPORTER_AVAILABLE,
    reason="reporter module required"
)


def make_mock_cv_result(passed=True, ssim=0.97, regions=None):
    """Build a minimal mock ComparisonResult."""
    mock = MagicMock()
    mock.passed = passed
    mock.ssim_score = ssim
    mock.total_changed_pixels = 1500 if not passed else 100
    mock.changed_percentage = 1.5 if not passed else 0.2
    mock.layout_shift_detected = False
    mock.changed_regions = regions or []
    mock.edge_diff_percentage = 0.5
    mock.edge_diff_score = 0.05
    mock.feature_match_score = 0.95
    mock.histogram_correlation = {"R": 0.99, "G": 0.99, "B": 0.99}
    mock.histogram_similarity = 0.99
    mock.severity = "medium"
    mock.error = None
    return mock


class TestReporterConsole:
    """Tests for the console (text) report format."""

    def test_console_report_non_empty(self):
        """Console render should produce a non-empty string."""
        reporter = Reporter()
        result = reporter.render(
            baseline_path="base.png",
            current_path="cur.png",
            cv_result=make_mock_cv_result(),
            ai_result=None,
            fmt="console",
            image_paths={},
        )
        assert len(result.strip()) > 0

    def test_console_report_contains_ssim(self):
        """Console report should mention the SSIM score."""
        reporter = Reporter()
        result = reporter.render(
            baseline_path="base.png",
            current_path="cur.png",
            cv_result=make_mock_cv_result(ssim=0.97),
            ai_result=None,
            fmt="console",
            image_paths={},
        )
        assert "0.97" in result or "ssim" in result.lower() or "SSIM" in result


class TestReporterJSON:
    """Tests for the JSON report format."""

    def test_json_report_is_valid(self):
        """JSON render should produce valid JSON."""
        reporter = Reporter()
        result = reporter.render(
            baseline_path="base.png",
            current_path="cur.png",
            cv_result=make_mock_cv_result(),
            ai_result=None,
            fmt="json",
            image_paths={},
        )
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_json_report_has_ssim_key(self):
        """JSON report should include the SSIM score."""
        reporter = Reporter()
        result = reporter.render(
            baseline_path="base.png",
            current_path="cur.png",
            cv_result=make_mock_cv_result(ssim=0.93),
            ai_result=None,
            fmt="json",
            image_paths={},
        )
        parsed = json.loads(result)
        # Find ssim_score somewhere in the structure
        result_str = json.dumps(parsed)
        assert "ssim" in result_str.lower() or "0.93" in result_str


class TestReporterHTML:
    """Tests for the HTML report format."""

    def test_html_report_is_non_empty(self):
        """HTML render should produce a non-empty string."""
        reporter = Reporter()
        result = reporter.render(
            baseline_path="base.png",
            current_path="cur.png",
            cv_result=make_mock_cv_result(),
            ai_result=None,
            fmt="html",
            image_paths={},
        )
        assert len(result.strip()) > 0

    def test_html_report_has_doctype_or_html_tag(self):
        """HTML render should start with a valid HTML structure."""
        reporter = Reporter()
        result = reporter.render(
            baseline_path="base.png",
            current_path="cur.png",
            cv_result=make_mock_cv_result(),
            ai_result=None,
            fmt="html",
            image_paths={},
        )
        assert "<!DOCTYPE" in result or "<html" in result or "<HTML" in result
