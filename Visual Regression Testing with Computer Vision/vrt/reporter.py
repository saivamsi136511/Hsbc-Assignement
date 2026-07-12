"""
vrt/reporter.py
===============
Report rendering layer for the Visual Regression Testing package.

Generates three output formats from a ``ComparisonResult`` and optional
``AIAnalysisResult``:

- **console** — Colour-coded terminal output with severity badges.
- **html**    — Self-contained dark-themed HTML report with side-by-side
                image comparison, diff heatmap, and an issue table.
- **json**    — Machine-readable output for CI/CD pipeline integration.

This module re-exports ``Reporter`` from the canonical flat file
``reporter.py`` so it can be imported from the package path.
"""

try:
    from reporter import Reporter
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from reporter import Reporter

__all__ = ["Reporter"]
