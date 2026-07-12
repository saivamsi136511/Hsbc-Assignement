"""
services/triage_service.py
===========================
High-level triaging orchestration for the Intelligent Bug Triaging system.

The ``TriagingEngine`` is the single entry point for converting a raw
``BugReport`` into a fully triaged ``Ticket``.  It follows a two-phase strategy:

1. **Heuristic phase** (always runs, zero latency): keyword-based scoring
   assigns category, urgency, severity, and confidence instantly without any
   network call.

2. **LLM enrichment phase** (optional, async-friendly): if the configured
   LLM backend is reachable, a structured JSON request is sent and the
   response is merged on top of the heuristic result.  LLM values take
   precedence for fields where they are non-empty.

If the LLM is unreachable or returns a malformed response, the heuristic
result is used unchanged — triage is never blocked or degraded by LLM issues.

This module re-exports ``TriagingEngine`` from the original flat
``triaging_engine.py`` for backward compatibility, while providing the
new package-path import for the layered architecture.
"""

from __future__ import annotations

# Re-export from the canonical flat module for backward compatibility.
# The original triaging_engine.py remains the implementation source.
try:
    from triaging_engine import TriagingEngine
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from triaging_engine import TriagingEngine

__all__ = ["TriagingEngine"]
