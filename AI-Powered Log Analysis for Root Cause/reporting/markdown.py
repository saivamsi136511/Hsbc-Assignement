"""
reporting/markdown.py
=====================
Markdown report renderer for the AI-Powered Log Analysis system.

Produces GitHub-compatible Markdown suitable for sharing as a gist,
pasting into a PR comment, or committing to a repository.  Uses ``<details>``
blocks for the dry-run context view so the report stays compact.

This module re-exports ``render_markdown`` from the canonical flat file
``log_analyzer.py`` so it can be imported from the package path.
"""

try:
    from log_analyzer import render_markdown
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from log_analyzer import render_markdown

__all__ = ["render_markdown"]
