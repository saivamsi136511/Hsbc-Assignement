"""
ingestion/parsers.py
====================
Multi-format streaming log parser for the AI-Powered Log Analysis system.

Supports four structured log formats natively:
- **Python** — ``Traceback (most recent call last):`` style tracebacks
- **Java**   — ``at package.Class.method(File.java:line)`` stack traces
- **Node.js** — V8 ``at Object.<anonymous> (file.js:line:col)`` format
- **Go**     — ``goroutine N [running]:`` panic traces

Any log that does not match a structured format falls back to a generic
detector that groups contiguous ``ERROR``/``FATAL``/``PANIC``-flagged lines.

This module re-exports the parsing API from the canonical flat file
``parsers.py`` so it can be imported from the new package structure.
"""

try:
    from parsers import (
        ParsedError,
        StackFrame,
        iter_parse_file,
        iter_parse_lines,
        parse_generic,
        dedupe,
    )
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from parsers import (
        ParsedError,
        StackFrame,
        iter_parse_file,
        iter_parse_lines,
        parse_generic,
        dedupe,
    )

__all__ = [
    "ParsedError",
    "StackFrame",
    "iter_parse_file",
    "iter_parse_lines",
    "parse_generic",
    "dedupe",
]
