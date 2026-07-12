"""
vrt/processor.py
================
Multi-layer OpenCV image comparison engine for the VRT package.

The ``ImageProcessor`` performs five independent analyses on a pair of
screenshots, combining their signals to produce a comprehensive, false-
positive-resistant comparison result:

1. **SSIM** (Structural Similarity Index) — overall perceptual quality score
2. **ORB feature matching** — detects layout shifts (element displacement > 20px)
3. **Canny edge-map diff** — detects missing or newly added structural elements
4. **Contour-based region detection** — groups changed pixels into bounding boxes
5. **Colour histogram comparison** — catches stylesheet/theme/palette regressions

This module re-exports ``ImageProcessor`` from the canonical flat file
``image_processor.py`` so it can be imported from the package path.
"""

try:
    from image_processor import ImageProcessor, ComparisonResult, ChangedRegion
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from image_processor import ImageProcessor, ComparisonResult, ChangedRegion

__all__ = ["ImageProcessor", "ComparisonResult", "ChangedRegion"]
