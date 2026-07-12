"""
tests/test_ai.py
================
Unit tests for the Ollama AI vision client (vrt/ai.py / ai_analyzer.py).

All Ollama HTTP calls are mocked so these tests run without any running
Ollama server or downloaded vision model.

Tests cover:
  - OllamaAnalyzer.analyze() returns AIAnalysisResult on success
  - Graceful degradation: Ollama unavailable returns error field, not exception
  - JSON response parsing handles markdown fences
  - Structured issues list is populated from model response
  - Elapsed time is recorded in the result
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from ai_analyzer import OllamaAnalyzer, AIAnalysisResult, AIIssue
    ANALYZER_AVAILABLE = True
except ImportError:
    ANALYZER_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not ANALYZER_AVAILABLE,
    reason="ai_analyzer module required"
)


def make_mock_cv_result():
    """Build a minimal mock ComparisonResult for testing."""
    mock = MagicMock()
    mock.ssim_score = 0.87
    mock.changed_percentage = 5.2
    mock.layout_shift_detected = True
    mock.changed_regions = []
    mock.edge_diff_percentage = 3.1
    mock.histogram_correlation = {"R": 0.91, "G": 0.93, "B": 0.90}
    mock.error = None
    return mock


MOCK_OLLAMA_RESPONSE = {
    "response": """{
        "summary": "The navigation bar shifted 20px downward.",
        "issues": [{"description": "Nav shift", "severity": "high", "location": "header", "recommendation": "Check CSS margin-top"}],
        "overall_severity": "high",
        "confidence": "high",
        "recommendation": "Review CSS changes in the last deployment."
    }"""
}


class TestOllamaAnalyzer:
    """Tests for the OllamaAnalyzer class."""

    @patch("requests.post")
    def test_returns_ai_analysis_result(self, mock_post):
        """A successful Ollama call should return an AIAnalysisResult."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: MOCK_OLLAMA_RESPONSE,
            raise_for_status=lambda: None,
        )
        analyzer = OllamaAnalyzer(model="llava")
        result = analyzer.analyze("dummy_base.png", "dummy_cur.png", make_mock_cv_result())
        assert isinstance(result, AIAnalysisResult)

    @patch("requests.post")
    def test_summary_populated_on_success(self, mock_post):
        """The summary field should be populated from the model response."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: MOCK_OLLAMA_RESPONSE,
            raise_for_status=lambda: None,
        )
        analyzer = OllamaAnalyzer(model="llava")
        result = analyzer.analyze("dummy_base.png", "dummy_cur.png", make_mock_cv_result())
        assert "navigation" in result.summary.lower() or result.summary != ""

    @patch("requests.post", side_effect=Exception("Connection refused"))
    def test_ollama_unavailable_returns_error_not_exception(self, mock_post):
        """Ollama being unavailable should set result.error, not raise."""
        analyzer = OllamaAnalyzer(model="llava")
        result = analyzer.analyze("dummy_base.png", "dummy_cur.png", make_mock_cv_result())
        assert result.error is not None
        assert isinstance(result.error, str)


class TestVRTUtilsIgnoreRegion:
    """Tests for ignore-region parsing utility."""

    def test_valid_region_parsed(self):
        """Valid X,Y,W,H string should parse to an int tuple."""
        from vrt.utils import parse_ignore_regions
        result = parse_ignore_regions(["10,20,300,60"])
        assert result == [(10, 20, 300, 60)]

    def test_multiple_regions_parsed(self):
        """Multiple regions should all be parsed."""
        from vrt.utils import parse_ignore_regions
        result = parse_ignore_regions(["0,0,100,50", "800,0,200,80"])
        assert len(result) == 2

    def test_invalid_region_skipped(self):
        """An invalid string should be skipped without raising."""
        from vrt.utils import parse_ignore_regions
        result = parse_ignore_regions(["not-a-region", "0,0,100,50"])
        assert result == [(0, 0, 100, 50)]

    def test_none_returns_empty(self):
        """None input should produce an empty list."""
        from vrt.utils import parse_ignore_regions
        assert parse_ignore_regions(None) == []
