"""
reporting
=========
Report rendering layer for the AI-Powered Log Analysis system.

Converts a list of ``Finding`` objects (each containing a ``ParsedError``,
context metadata, and an ``AnalysisResult``) into human-readable output.

Modules:
    console     — Colour-coded terminal output
    markdown    — GitHub-compatible Markdown report generation
    json_report — Machine-readable JSON output for CI/CD pipelines
"""
