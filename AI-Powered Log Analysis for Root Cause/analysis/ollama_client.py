"""
analysis/ollama_client.py
=========================
Local Ollama LLM backend for the AI-Powered Log Analysis system.

Uses only the Python standard library (no ``requests`` or ``anthropic``
dependency) so it works without any pip install on a machine that already
has Ollama running.

Ollama is the **default backend** — free, local, zero data egress, and
GDPR-friendly.  Run ``ollama serve`` and ``ollama pull llama3.1`` to use it.

This module re-exports ``OllamaBackend`` from the canonical flat file
``ollama_client.py`` so it can be imported from the package path.
"""

try:
    from ollama_client import OllamaBackend, DEFAULT_MODEL
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from ollama_client import OllamaBackend, DEFAULT_MODEL

__all__ = ["OllamaBackend", "DEFAULT_MODEL"]
