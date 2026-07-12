"""
services
========
Business logic layer for the Intelligent Bug Triaging system.

Contains the triaging pipeline, NLP heuristics, and LLM client wrappers.

Modules:
    triage_service — High-level triaging orchestration (heuristics + LLM)
    heuristics     — Keyword-based category, urgency, and severity scoring
    llm_clients    — OllamaClient and OpenAICompatClient wrappers
"""
