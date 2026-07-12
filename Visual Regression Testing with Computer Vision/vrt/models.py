"""
vrt/models.py
=============
Data models for the Visual Regression Testing package.

Defines the structured result objects produced by each layer of the pipeline
so that the reporting layer can consume them without knowledge of how
they were computed.

Classes
-------
ChangedRegion   — A single bounding-box area of detected visual change
ComparisonResult — Full OpenCV analysis output (SSIM, ORB, edges, regions, etc.)
AIIssue         — A single visual issue identified by the AI vision model
AIAnalysisResult — Structured output from the Ollama vision model
"""

# Re-export from canonical flat modules for backward compatibility.
try:
    from image_processor import ComparisonResult, ChangedRegion
    from ai_analyzer import AIAnalysisResult, AIIssue
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from image_processor import ComparisonResult, ChangedRegion
    from ai_analyzer import AIAnalysisResult, AIIssue

__all__ = ["ComparisonResult", "ChangedRegion", "AIAnalysisResult", "AIIssue"]
