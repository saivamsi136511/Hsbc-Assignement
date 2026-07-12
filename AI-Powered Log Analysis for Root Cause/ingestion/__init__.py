"""
ingestion
=========
Log ingestion layer for the AI-Powered Log Analysis system.

Handles reading log files, parsing structured error records from multiple
log formats, and deduplicating repeated occurrences of the same error.

Modules:
    parsers — Multi-format streaming parser (Python, Java, Node, Go, generic)
    dedup   — Fingerprint-based deduplication helpers
"""
