"""
vrt/ai.py
=========
Local Ollama vision model client for the VRT package.

Sends the baseline screenshot, current screenshot, and diff heatmap to a
locally-running Ollama vision model (e.g. ``llava``, ``moondream``) along
with quantitative OpenCV metrics as grounding context.

The model produces:
- A plain-English summary of what visually changed and its significance
- Per-issue descriptions with location hints and severity grades
- An overall actionable recommendation for the development team

**Zero data leaves your machine** — no Anthropic, no OpenAI, no cloud calls.

This module re-exports ``OllamaAnalyzer`` from the canonical flat file
``ai_analyzer.py`` so it can be imported from the package path.
"""

try:
    from ai_analyzer import OllamaAnalyzer, AIAnalysisResult, AIIssue, DEFAULT_MODEL
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from ai_analyzer import OllamaAnalyzer, AIAnalysisResult, AIIssue, DEFAULT_MODEL

__all__ = ["OllamaAnalyzer", "AIAnalysisResult", "AIIssue", "DEFAULT_MODEL"]
