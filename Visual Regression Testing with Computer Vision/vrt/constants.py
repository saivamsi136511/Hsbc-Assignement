"""
vrt/constants.py
================
Centralized constants for the Visual Regression Testing package.

All default values, thresholds, model names, and configuration strings are
defined here. Import from this module rather than scattering literals across
the codebase.
"""

from typing import Tuple

# ---------------------------------------------------------------------------
# Ollama / AI defaults
# ---------------------------------------------------------------------------

DEFAULT_MODEL: str = "llava"
"""Default Ollama vision model. llava supports image inputs and is ~4 GB."""

OLLAMA_BASE_URL: str = "http://localhost:11434"
"""Default base URL for the local Ollama server."""

AI_REQUEST_TIMEOUT: int = 120
"""Seconds to wait for an Ollama vision model response (can be slow on CPU)."""

OLLAMA_API_GENERATE_PATH: str = "/api/generate"
"""REST path for Ollama's text/vision generation endpoint."""

# ---------------------------------------------------------------------------
# SSIM / comparison defaults
# ---------------------------------------------------------------------------

DEFAULT_SSIM_THRESHOLD: float = 0.95
"""
SSIM score at or above which the test is considered passed.
Range 0.0–1.0. Lower = more permissive (fewer false failures).
"""

DEFAULT_MIN_CHANGE_AREA: int = 100
"""
Minimum changed-region area in pixels to be reported.
Regions smaller than this are treated as anti-aliasing noise and filtered out.
"""

GAUSSIAN_BLUR_KERNEL: Tuple[int, int] = (3, 3)
"""Kernel size for Gaussian blur applied before comparison to reduce sub-pixel noise."""

DILATION_KERNEL_SIZE: Tuple[int, int] = (5, 5)
"""Kernel size used to dilate changed-pixel regions so nearby changes merge."""

DILATION_ITERATIONS: int = 2
"""Number of dilation passes applied when merging nearby changed regions."""

# ---------------------------------------------------------------------------
# ORB feature matching
# ---------------------------------------------------------------------------

ORB_N_FEATURES: int = 500
"""Number of ORB keypoints to detect in each image."""

ORB_MATCH_DISTANCE_THRESHOLD: float = 50.0
"""Maximum Hamming distance for an ORB descriptor match to be considered valid."""

ORB_LAYOUT_SHIFT_THRESHOLD: float = 20.0
"""
Minimum average keypoint displacement (pixels) to flag a layout shift.
Displacements below this are sub-pixel and not considered meaningful.
"""

ORB_MATCH_RATIO_THRESHOLD: float = 0.15
"""
Fraction of ORB keypoints that must match for the comparison to produce
a meaningful layout-shift estimate.
"""

# ---------------------------------------------------------------------------
# Edge map (Canny) defaults
# ---------------------------------------------------------------------------

CANNY_THRESHOLD_1: int = 100
"""Lower hysteresis threshold for the Canny edge detector."""

CANNY_THRESHOLD_2: int = 200
"""Upper hysteresis threshold for the Canny edge detector."""

EDGE_DIFF_SIGNIFICANT_THRESHOLD: float = 5.0
"""
Percentage of differing edge pixels above which a structural-element
change (element added or removed) is flagged.
"""

# ---------------------------------------------------------------------------
# Colour histogram comparison
# ---------------------------------------------------------------------------

HISTOGRAM_BINS: int = 256
"""Number of bins per channel for colour histogram computation."""

HISTOGRAM_CORRELATION_THRESHOLD: float = 0.95
"""
Per-channel histogram correlation below which a colour/stylesheet
regression is flagged. Correlation of 1.0 = identical; 0.0 = unrelated.
"""

# ---------------------------------------------------------------------------
# Severity classification thresholds
# ---------------------------------------------------------------------------

REGION_SEVERITY_HIGH_THRESHOLD: float = 100.0
"""Mean pixel intensity delta above which a region is classified as 'high' severity."""

REGION_SEVERITY_MEDIUM_THRESHOLD: float = 50.0
"""Mean pixel intensity delta above which a region is classified as 'medium' severity."""

# ---------------------------------------------------------------------------
# Output / reporting defaults
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_DIR: str = "vrt_output"
"""Default directory for saving diff, heatmap, and annotated output images."""

DEFAULT_REPORT_FORMAT: str = "console"
"""Default report format when no --format flag is provided."""

SUPPORTED_FORMATS: Tuple[str, ...] = ("console", "html", "json")
"""All supported report output formats."""

DIFF_IMAGE_FILENAME: str = "diff.png"
"""Filename for the raw pixel-difference image saved to the output directory."""

HEATMAP_IMAGE_FILENAME: str = "heatmap.png"
"""Filename for the colour-coded diff heatmap image."""

ANNOTATED_IMAGE_FILENAME: str = "annotated.png"
"""Filename for the current screenshot annotated with bounding boxes."""

# ---------------------------------------------------------------------------
# Prompt engineering
# ---------------------------------------------------------------------------

MAX_PROMPT_IMAGE_SIZE_PX: int = 1024
"""Images larger than this (on the longest side) are resized before being
sent to the vision model to avoid exceeding context limits."""
