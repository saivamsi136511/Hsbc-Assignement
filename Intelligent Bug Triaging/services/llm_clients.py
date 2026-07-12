"""
services/llm_clients.py
=======================
LLM client adapters for the Intelligent Bug Triaging system.

Provides two clients that share the same interface (a ``triage`` method
that accepts a ``BugReport`` and returns a triage-result dict):

- ``OllamaClient``          — free, local, uses the Ollama HTTP API.
- ``OpenAICompatClient``    — any OpenAI-compatible API (also works with
                              LM Studio, vLLM, etc.).

Both clients include:
- ``is_available()`` to pre-flight-check reachability.
- Defensive JSON parsing that handles model responses with stray markdown fences.
- Clear exception (``LLMUnavailable``) instead of raw network errors.

The ``TriagingEngine`` (in ``services/triage_service.py``) always runs the
heuristic first, then overlays LLM results when available — so neither
client is a single point of failure.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict


# ---------------------------------------------------------------------------
# LLM system prompt (shared by both clients)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an expert software engineering triage assistant.
A user has submitted a bug report. Analyze it and respond with ONLY a single
JSON object — no markdown fences, no prose before or after — with exactly
these keys:

{
  "category": "one of: UI | Backend | Database | Authentication | Security | Performance | Network | Mobile | Infrastructure | Unknown",
  "severity": "one of: Critical | High | Medium | Low",
  "urgency_level": "one of: Critical | High | Medium | Low",
  "urgency_score": <integer 0-100>,
  "summary": "1-2 sentence plain English summary of the bug",
  "suggested_fix": "concrete actionable suggestion to fix or investigate the issue",
  "confidence": <integer 0-100>
}

Rules:
- severity=Critical if production is down, all users are affected, data loss, payment failure, or security breach
- severity=High if a major feature is broken for many users
- severity=Medium if intermittent or affecting some users
- severity=Low if cosmetic / minor / enhancement
- urgency_score reflects time-sensitivity (100 = immediate)
"""


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class LLMUnavailable(Exception):
    """
    Raised when an LLM client cannot reach the server, the model is not
    found, or the server returns a non-2xx response.

    The ``TriagingEngine`` catches this and falls back to the heuristic result.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_llm_json(content: str) -> Dict[str, Any]:
    """
    Defensively parse a JSON response from an LLM.

    Tries three strategies in order:
    1. Parse the raw content directly.
    2. Strip markdown code fences (``` json ... ```) and parse again.
    3. Extract the first ``{...}`` block with a regex and parse that.

    Args:
        content: Raw string response from the LLM.

    Returns:
        A parsed dict if any strategy succeeds, or an empty dict if all fail.
    """
    content = content.strip()
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.MULTILINE)
    for attempt in (content, stripped):
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{.*\}", content, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass
    return {}


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------

class OllamaClient:
    """
    Client for locally running Ollama server.

    Communicates with Ollama's ``/api/chat`` endpoint using the Python
    standard library (no third-party dependencies), so it works in
    resource-constrained environments without pip.

    Args:
        base_url: Base URL of the Ollama server (default: http://localhost:11434).
        model:    Ollama model name (e.g. ``"llama3.1"``).
        timeout:  Request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.1",
        timeout: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        """
        Check whether the Ollama server is reachable.

        Returns:
            ``True`` if ``GET /api/tags`` returns HTTP 200, ``False`` otherwise.
        """
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _post(self, path: str, payload: dict) -> dict:
        """
        POST a JSON payload to an Ollama endpoint and return the parsed response.

        Args:
            path:    URL path relative to ``base_url`` (e.g. ``"/api/chat"``).
            payload: Dict to JSON-serialise and send as the request body.

        Returns:
            Parsed JSON response as a dict.

        Raises:
            LLMUnavailable: On HTTP errors or network failures.
        """
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 404 or "not found" in body.lower():
                raise LLMUnavailable(
                    f"Model '{self.model}' not found. Run: ollama pull {self.model}"
                ) from exc
            raise LLMUnavailable(f"Ollama HTTP {exc.code}: {body[:200]}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise LLMUnavailable(
                f"Cannot reach Ollama at {self.base_url}: {exc}"
            ) from exc

    def triage(self, report) -> Dict[str, Any]:
        """
        Triage a bug report using the local Ollama model.

        Sends the bug title and description as a user message and parses the
        model's JSON response into a triage result dict.

        Args:
            report: A ``BugReport`` instance with ``title`` and ``description``.

        Returns:
            A parsed dict from the LLM response, or empty dict on parse failure.

        Raises:
            LLMUnavailable: If the network request fails.
        """
        user_msg = f"Bug Report Title: {report.title}\n\nBug Description:\n{report.description}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
        result = self._post("/api/chat", payload)
        content = result.get("message", {}).get("content", "")
        return _parse_llm_json(content)


# ---------------------------------------------------------------------------
# OpenAI-compatible client
# ---------------------------------------------------------------------------

class OpenAICompatClient:
    """
    Client for any OpenAI-compatible chat completion API.

    Works with the OpenAI API, Azure OpenAI, LM Studio, vLLM, and any other
    service implementing the ``/chat/completions`` endpoint.

    Args:
        base_url: API base URL (e.g. ``"https://api.openai.com/v1"``).
        model:    Model name (e.g. ``"gpt-4o-mini"``).
        api_key:  API authentication key (passed as Bearer token).
        timeout:  Request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def is_available(self) -> bool:
        """
        Check whether the API endpoint is reachable.

        Returns:
            ``True`` if ``GET /models`` returns HTTP 200, ``False`` otherwise.
        """
        try:
            req = urllib.request.Request(f"{self.base_url}/models")
            if self.api_key:
                req.add_header("Authorization", f"Bearer {self.api_key}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def triage(self, report) -> Dict[str, Any]:
        """
        Triage a bug report using the OpenAI-compatible API.

        Args:
            report: A ``BugReport`` instance with ``title`` and ``description``.

        Returns:
            A parsed dict from the API response.

        Raises:
            LLMUnavailable: If the network request fails.
        """
        user_msg = f"Bug Report Title: {report.title}\n\nBug Description:\n{report.description}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=data,
            headers={"Content-Type": "application/json"},
        )
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise LLMUnavailable(f"Cannot reach {self.base_url}: {exc}") from exc
        content = result["choices"][0]["message"]["content"]
        return _parse_llm_json(content)
