"""
analysis/pipeline.py
====================
Full orchestration pipeline for the AI-Powered Log Analysis system.

The pipeline coordinates all stages of the analysis in sequence:
1. **Ingest**    — Read the log file (or stdin) and parse structured errors
2. **Deduplicate** — Collapse repeated occurrences into single entries
3. **Contextualize** — Assemble a token-budgeted prompt payload per error
4. **Analyze**   — Send to the configured LLM backend and parse the response
5. **Report**    — Render findings to console, Markdown, or JSON

This module re-exports the ``run`` function from the canonical flat
``log_analyzer.py`` so it can be imported from the package path.
"""

try:
    from log_analyzer import run, Finding, collect_errors, build_backend
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from log_analyzer import run, Finding, collect_errors, build_backend

__all__ = ["run", "Finding", "collect_errors", "build_backend"]
