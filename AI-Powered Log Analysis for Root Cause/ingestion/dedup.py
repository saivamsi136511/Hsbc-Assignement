"""
ingestion/dedup.py
==================
Deduplication helpers for the AI-Powered Log Analysis system.

Log files often contain the same exception repeated hundreds of times
(e.g. a retry loop that fails on every attempt).  Without deduplication,
every repetition would be sent to the LLM separately, wasting tokens and
producing redundant output.

This module re-exports the ``dedupe`` function from the canonical flat
``parsers.py`` module so it can also be imported from the package path.

The deduplication strategy:
- Groups errors by a fingerprint derived from ``(error_type, message, top_frame)``.
- Each unique fingerprint is kept once; the ``occurrence_count`` field of the
  ``ParsedError`` records how many times it appeared in the original log.
"""

try:
    from parsers import dedupe
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from parsers import dedupe

__all__ = ["dedupe"]
