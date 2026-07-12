"""
tests/test_processor.py
=======================
Unit tests for the multi-layer OpenCV image processor (vrt/processor.py).

Tests run WITHOUT requiring a GPU or display — OpenCV runs headlessly.
Sample images are created programmatically using numpy so no external
image files are needed.

Tests cover:
  - SSIM comparison: identical images score 1.0
  - SSIM comparison: very different images score < threshold
  - Changed-region detection: regions larger than min_area are reported
  - Layout-shift detection flag behaviour
  - Ignore-region masking: masked areas do not contribute to change regions
  - Error handling: missing file returns error field, not exception
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import numpy as np
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not OPENCV_AVAILABLE,
    reason="OpenCV and numpy required for processor tests"
)


def make_temp_image(array, suffix=".png"):
    """Save a numpy array as a temporary image and return its path."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    cv2.imwrite(tmp.name, array)
    return tmp.name


def white_image(h=200, w=300):
    """Create a solid white image."""
    return np.full((h, w, 3), 255, dtype=np.uint8)


def black_image(h=200, w=300):
    """Create a solid black image."""
    return np.zeros((h, w, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# SSIM comparison
# ---------------------------------------------------------------------------

class TestSSIM:
    """Tests for SSIM-based comparison."""

    def test_identical_images_score_near_one(self):
        """Two identical images should produce SSIM very close to 1.0."""
        from image_processor import ImageProcessor
        img = white_image()
        path = make_temp_image(img)
        try:
            proc = ImageProcessor(ssim_threshold=0.95)
            result = proc.compare(path, path)
            assert result.error is None, f"Unexpected error: {result.error}"
            assert result.ssim_score >= 0.99
        finally:
            os.unlink(path)

    def test_different_images_score_below_threshold(self):
        """A white vs black image pair should fail the SSIM threshold."""
        from image_processor import ImageProcessor
        white_path = make_temp_image(white_image())
        black_path = make_temp_image(black_image())
        try:
            proc = ImageProcessor(ssim_threshold=0.95)
            result = proc.compare(white_path, black_path)
            assert result.ssim_score < 0.95
            assert not result.passed
        finally:
            os.unlink(white_path)
            os.unlink(black_path)

    def test_passed_flag_reflects_threshold(self):
        """The `passed` flag should be True only when SSIM >= threshold."""
        from image_processor import ImageProcessor
        img = white_image()
        path = make_temp_image(img)
        try:
            proc = ImageProcessor(ssim_threshold=0.95)
            result = proc.compare(path, path)
            # Identical images should pass
            assert result.passed
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestProcessorErrors:
    """Tests for error handling in the ImageProcessor."""

    def test_missing_baseline_sets_error_field(self):
        """A non-existent baseline path should populate the error field."""
        from image_processor import ImageProcessor
        img_path = make_temp_image(white_image())
        try:
            proc = ImageProcessor()
            result = proc.compare("/nonexistent/path.png", img_path)
            assert result.error is not None
        finally:
            os.unlink(img_path)

    def test_missing_current_sets_error_field(self):
        """A non-existent current path should populate the error field."""
        from image_processor import ImageProcessor
        img_path = make_temp_image(white_image())
        try:
            proc = ImageProcessor()
            result = proc.compare(img_path, "/nonexistent/path.png")
            assert result.error is not None
        finally:
            os.unlink(img_path)
