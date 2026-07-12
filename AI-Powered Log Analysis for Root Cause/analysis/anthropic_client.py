"""
analysis/anthropic_client.py
============================
Anthropic Claude API backend for the AI-Powered Log Analysis system.

Higher quality than local Ollama models for nuanced root-cause analysis,
but requires an ``ANTHROPIC_API_KEY`` and sends log data (redacted by default)
to Anthropic's servers.

Usage:
    python log_analyzer.py crash.log --backend anthropic

This module re-exports ``AnthropicBackend`` from the canonical flat file
``ai_client.py`` so it can be imported from the package path.
"""

try:
    from ai_client import AnthropicBackend, DEFAULT_MODEL
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from ai_client import AnthropicBackend, DEFAULT_MODEL

__all__ = ["AnthropicBackend", "DEFAULT_MODEL"]
