"""
testgen
=======
Package for AI-powered automated test case generation from user stories.

Modules:
    constants    — Shared constants (URLs, defaults, limits)
    config       — CLI configuration dataclass
    prompts      — LLM system / user / batch / fix prompt builders
    ollama_client — Streaming Ollama HTTP client with retry/backoff
    parser       — Acceptance-criteria extraction and chunking
    generator    — Single-shot and batched generation pipelines
    merge        — AST-based multi-batch module merger
    output       — Code extraction, syntax validation, and summarization
"""

__version__ = "1.0.0"
__author__ = "HSBC QA Engineering"
