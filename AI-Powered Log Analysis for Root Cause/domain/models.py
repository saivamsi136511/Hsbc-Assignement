"""
domain/models.py
================
Core domain models for the AI-Powered Log Analysis system.

This module re-exports the primary data classes used throughout the pipeline
from the canonical flat-file implementation (``analysis_common.py`` and
``parsers.py``) so they can also be imported from the new package structure.

Data classes
------------
ParsedError     — A single extracted error/exception from a log file
StackFrame      — A single frame in a stack trace
AnalysisResult  — Structured output from the AI analysis backend
Finding         — Bundles ParsedError + context + budget + AnalysisResult
"""

# Re-export from canonical flat modules for backward compatibility.
try:
    from parsers import ParsedError, StackFrame
    from analysis_common import AnalysisResult
    from log_analyzer import Finding
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from parsers import ParsedError, StackFrame
    from analysis_common import AnalysisResult
    from log_analyzer import Finding

__all__ = ["ParsedError", "StackFrame", "AnalysisResult", "Finding"]
