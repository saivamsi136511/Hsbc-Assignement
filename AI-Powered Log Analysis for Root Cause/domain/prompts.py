"""
domain/prompts.py
=================
Shared LLM system prompt and JSON output schema for the log analysis pipeline.

Both the Ollama backend (``analysis/ollama_client.py``) and the Anthropic
backend (``analysis/anthropic_client.py``) use the same system prompt and
expect the same JSON output schema, making backend results interchangeable.

This module re-exports the shared prompt from the canonical implementation
in ``analysis_common.py``.

Exports
-------
SYSTEM_PROMPT   — Instructs the LLM to produce structured JSON analysis
JSON_SCHEMA     — Expected output schema documentation string
"""

try:
    from analysis_common import SYSTEM_PROMPT
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from analysis_common import SYSTEM_PROMPT

# The JSON output schema the model is expected to follow.
JSON_SCHEMA = """
{
  "summary":       "<1-2 sentence plain-English summary of the error>",
  "likely_file":   "<path to the likely offending source file, or null>",
  "likely_line":   <line number as integer, or null>,
  "root_cause":    "<hypothesis for what caused this error>",
  "confidence":    "<high | medium | low>",
  "suggested_fix": "<concrete actionable suggestion for fixing or investigating>",
  "workaround":    "<temporary workaround if any, or null>",
  "severity":      "<critical | high | medium | low>"
}
"""
"""
Expected JSON output schema.  Both backends are instructed to produce exactly
this structure so that the reporting layer is backend-agnostic.
"""

__all__ = ["SYSTEM_PROMPT", "JSON_SCHEMA"]
