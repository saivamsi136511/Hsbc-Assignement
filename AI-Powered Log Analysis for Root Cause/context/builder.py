"""
context/builder.py
==================
Token-budgeted context assembly for the AI-Powered Log Analysis system.

For each distinct error extracted from a log file, this module assembles the
text payload that will be sent to the LLM.  Context is assembled in priority
order to stay within a configurable token budget:

1. Error type + message (always included)
2. Stack trace (truncated for deep recursion / stack overflows)
3. Real source code around the likely offending frame (if --source-dir given)
4. Preceding log lines (fills remaining budget)

Token counting uses a ``chars / 4`` heuristic — accurate enough for the
prioritisation decisions made here without requiring a tokeniser dependency.

This module re-exports the public API from the canonical flat file
``context_builder.py`` so it can be imported from the package path.
"""

try:
    from context_builder import build_prompt_context, ContextBudgetReport, redact
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from context_builder import build_prompt_context, ContextBudgetReport, redact

__all__ = ["build_prompt_context", "ContextBudgetReport", "redact"]
