"""
analysis
========
AI analysis layer for the AI-Powered Log Analysis system.

Orchestrates the end-to-end pipeline (parse → context → analyze → render)
and provides pluggable LLM backends.

Modules:
    pipeline          — Full orchestration: ingestion → context → LLM → report
    ollama_client     — Free local Ollama backend (default, no API key needed)
    anthropic_client  — Claude API backend (higher quality, requires API key)
"""
