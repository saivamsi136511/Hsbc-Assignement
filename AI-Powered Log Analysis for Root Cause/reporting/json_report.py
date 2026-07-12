"""
reporting/json_report.py
========================
JSON report renderer for the AI-Powered Log Analysis system.

Produces machine-readable JSON output suitable for CI/CD pipeline
integration, programmatic consumption, or storage in a database.

Each finding is serialized as an object in an ``"issues"`` array with
all structured fields from the analysis (summary, likely_file, root_cause,
confidence, suggested_fix, etc.).

This module re-exports ``render_json`` from the canonical flat file
``log_analyzer.py`` so it can be imported from the package path.
"""

try:
    from log_analyzer import render_json
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from log_analyzer import render_json

__all__ = ["render_json"]
