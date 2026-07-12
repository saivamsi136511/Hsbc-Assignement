"""
reporting/console.py
====================
Console (terminal) report renderer for the AI-Powered Log Analysis system.

Produces a plain-text, human-readable report suitable for terminal output
or piping to less/more.  Each finding is formatted as a numbered block with
clearly labelled fields.

This module re-exports ``render_console`` from the canonical flat file
``log_analyzer.py`` so it can be imported from the package path.
"""

try:
    from log_analyzer import render_console
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from log_analyzer import render_console

__all__ = ["render_console"]
