"""
vrt
===
Package for AI-powered Visual Regression Testing with Computer Vision.

Modules:
    constants — Shared defaults (thresholds, model names, timeouts)
    models    — ComparisonResult, AIAnalysisResult, AIIssue, ChangedRegion
    utils     — Logging helpers and ignore-region parsing utilities
    cli       — CLI argument parsing and orchestration entry point
    processor — Multi-layer OpenCV image comparison engine
    ai        — Local Ollama vision model client
    reporter  — Console / HTML / JSON report generation
"""

__version__ = "1.0.0"
__author__ = "HSBC QA Engineering"
