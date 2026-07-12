"""
context/redaction.py
====================
Secret and PII masking rules for the AI-Powered Log Analysis system.

Before any log context is sent to a remote LLM (or written to a report),
sensitive values are redacted using regex pattern matching.

Patterns covered (by default):
- API keys and bearer tokens  (e.g. ``Bearer sk-ant-...``)
- Generic high-entropy secrets (long alphanumeric strings after ``key=``)
- Email addresses
- Card-number-shaped strings (16-digit runs)
- AWS access key IDs (``AKIA...``)

Redaction is enabled by default.  Pass ``--no-redact`` to the CLI to
disable it (useful when logs are already known to be clean).

This module re-exports the ``redact`` function from the canonical flat file
``context_builder.py`` so it can also be imported from the package path.
"""

try:
    from context_builder import redact
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from context_builder import redact

__all__ = ["redact"]
