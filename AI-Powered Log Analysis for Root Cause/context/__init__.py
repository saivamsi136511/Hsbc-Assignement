"""
context
=======
Context assembly layer for the AI-Powered Log Analysis system.

Prepares the text payload sent to the LLM for each error, managing:
- Token budget allocation (prioritising the most valuable context)
- Source code snippet lookup (when --source-dir is provided)
- PII and secrets redaction (API keys, emails, card numbers)

Modules:
    builder   — Token-budgeted context assembly and source lookup
    redaction — Regex-based secret/PII masking rules
"""
