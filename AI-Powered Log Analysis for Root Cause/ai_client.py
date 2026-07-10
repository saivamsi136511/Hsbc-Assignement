"""
ai_client.py
============
Anthropic API backend. Wraps calls to the Claude API and turns the result
into a structured AnalysisResult via analysis_common (shared with the
Ollama backend so report rendering doesn't care which one produced it).

Kept separate from parsing/context so the rest of the tool can be tested
with --dry-run and no network/API key at all.
"""

from __future__ import annotations

import os
import time
from typing import Optional

from analysis_common import AnalysisResult, SYSTEM_PROMPT, parse_json_response

DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL,
                 max_retries: int = 2, request_timeout: float = 60.0):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.max_retries = max_retries
        self.request_timeout = request_timeout
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:
                raise RuntimeError(
                    "The 'anthropic' package is required for --backend anthropic. "
                    "Install it with: pip install anthropic"
                ) from e
            if not self.api_key:
                raise RuntimeError(
                    "No API key found. Set the ANTHROPIC_API_KEY environment variable "
                    "or pass --api-key (or use --backend ollama for free local analysis)."
                )
            self._client = anthropic.Anthropic(api_key=self.api_key, timeout=self.request_timeout)
        return self._client

    def analyze(self, context_text: str) -> AnalysisResult:
        client = self._get_client()
        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                response = client.messages.create(
                    model=self.model,
                    max_tokens=1000,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": context_text}],
                )
                text = "".join(
                    block.text for block in response.content if getattr(block, "type", None) == "text"
                )
                parsed = parse_json_response(text, backend=self.name, model=self.model)
                parsed.input_tokens = getattr(response.usage, "input_tokens", 0)
                parsed.output_tokens = getattr(response.usage, "output_tokens", 0)
                return parsed
            except Exception as e:  # noqa: BLE001 - surface any API/network error to the caller
                last_err = e
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
        return AnalysisResult.from_failure(
            f"API call failed after {self.max_retries + 1} attempts: {last_err}",
            backend=self.name, model=self.model,
        )


# Backwards-compatible alias (earlier version of this tool exposed AIClient directly)
AIClient = AnthropicBackend
