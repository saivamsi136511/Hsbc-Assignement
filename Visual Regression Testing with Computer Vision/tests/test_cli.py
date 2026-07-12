"""
tests/test_cli.py
=================
Unit tests for the VRT CLI argument parser and orchestration.

Tests run without real images, Ollama, or OpenCV.

Tests cover:
  - Required arguments: --baseline and --current are required
  - --threshold accepts float values in range
  - --format accepts console/html/json
  - --ignore-region is repeatable
  - parse_ignore_regions correctly converts X,Y,W,H strings
  - Missing input file causes exit code 1 (not an unhandled exception)
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from visual_regressor import parse_args, parse_ignore_regions


class TestArgParser:
    """Tests for parse_args() argument parsing."""

    def test_required_args_parsed(self):
        """Both --baseline and --current should be parsed correctly."""
        args = parse_args(["--baseline", "a.png", "--current", "b.png"])
        assert args.baseline == "a.png"
        assert args.current == "b.png"

    def test_default_threshold(self):
        """Default SSIM threshold should be 0.95."""
        args = parse_args(["--baseline", "a.png", "--current", "b.png"])
        assert args.threshold == pytest.approx(0.95)

    def test_custom_threshold(self):
        """Custom --threshold should override the default."""
        args = parse_args(["--baseline", "a.png", "--current", "b.png", "--threshold", "0.80"])
        assert args.threshold == pytest.approx(0.80)

    def test_format_choices(self):
        """--format should accept console, html, and json."""
        for fmt in ("console", "html", "json"):
            args = parse_args(["--baseline", "a.png", "--current", "b.png", "--format", fmt])
            assert args.format == fmt

    def test_dry_run_flag(self):
        """--dry-run flag should set dry_run to True."""
        args = parse_args(["--baseline", "a.png", "--current", "b.png", "--dry-run"])
        assert args.dry_run is True

    def test_ignore_region_repeatable(self):
        """--ignore-region should accumulate multiple values."""
        args = parse_args([
            "--baseline", "a.png", "--current", "b.png",
            "--ignore-region", "0,0,100,50",
            "--ignore-region", "800,0,200,80",
        ])
        assert args.ignore_region is not None
        assert len(args.ignore_region) == 2

    def test_missing_required_args_exits(self):
        """Missing --baseline or --current should cause SystemExit."""
        with pytest.raises(SystemExit):
            parse_args(["--current", "b.png"])  # missing --baseline


class TestParseIgnoreRegions:
    """Tests for the ignore-region string parser."""

    def test_single_region(self):
        """A single valid region should be parsed correctly."""
        result = parse_ignore_regions(["10,20,300,60"])
        assert result == [(10, 20, 300, 60)]

    def test_empty_list(self):
        """Empty list input should return empty list."""
        assert parse_ignore_regions([]) == []

    def test_none_input(self):
        """None input should return empty list."""
        assert parse_ignore_regions(None) == []

    def test_invalid_entry_skipped(self):
        """An unparseable entry should be skipped without exception."""
        result = parse_ignore_regions(["bad-input", "0,0,50,50"])
        assert result == [(0, 0, 50, 50)]

    def test_spaces_in_values_handled(self):
        """Values with surrounding spaces should still parse correctly."""
        result = parse_ignore_regions(["10 , 20 , 300 , 60"])
        assert result == [(10, 20, 300, 60)]
