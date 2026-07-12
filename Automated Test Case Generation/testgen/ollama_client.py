"""
testgen/ollama_client.py
========================
Streaming Ollama HTTP client for the test case generation pipeline.

Provides a single public function, ``call_ollama``, that sends a list of
chat messages to a locally running Ollama server using its /api/chat
endpoint with ``stream=True``.

Streaming is used intentionally: it means the HTTP read timeout applies to
the gap *between* successive tokens, not to the total generation time.
This prevents false timeout failures when a large model produces a long
response but is still actively generating tokens.

Retries with exponential back-off are applied automatically on transient
connection or timeout errors before the error is surfaced to the caller.
"""

import json
import time
from typing import Any, Dict, List

import requests

from testgen.constants import (
    OLLAMA_API_CHAT_PATH,
    BACKOFF_BASE_SECONDS,
)


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class OllamaError(RuntimeError):
    """
    Raised when the Ollama server returns an error, cannot be reached after
    all retry attempts, or the requested model is not available.
    """


# ---------------------------------------------------------------------------
# Main client function
# ---------------------------------------------------------------------------

def call_ollama(
    messages: List[Dict[str, str]],
    model: str,
    host: str,
    temperature: float,
    num_ctx: int,
    num_predict: int,
    connect_timeout: int,
    read_timeout: int,
    max_conn_retries: int,
) -> str:
    """
    Send a chat request to a locally running Ollama instance and return the
    full response content as a single string.

    Uses streaming (``stream=True``) so that the read timeout applies to the
    silence *between* tokens rather than to the entire generation.  This
    prevents false timeouts when the model is still generating a long response.

    Transient ``ConnectionError`` and ``Timeout`` errors are retried with
    exponential back-off up to ``max_conn_retries`` attempts.

    Args:
        messages:         List of ``{"role": ..., "content": ...}`` dicts
                          forming the conversation to send to the model.
        model:            Ollama model name (e.g. ``"qwen2.5-coder:7b"``).
        host:             Base URL of the Ollama server
                          (e.g. ``"http://localhost:11434"``).
        temperature:      Sampling temperature; 0.0–1.0 (lower = more
                          deterministic output, recommended ~0.2 for code).
        num_ctx:          Context window size in tokens to request from Ollama.
        num_predict:      Maximum tokens to generate; ``-1`` for unlimited.
        connect_timeout:  Seconds to wait for the initial TCP connection.
        read_timeout:     Seconds of silence between streamed tokens before
                          treating the connection as stalled.
        max_conn_retries: Maximum total attempts (including the first) before
                          raising ``OllamaError``.

    Returns:
        The complete assistant response as a single concatenated string.

    Raises:
        OllamaError: If the model is not found (HTTP 404), the server returns
                     an API error, or all retry attempts are exhausted.
    """
    url = f"{host.rstrip('/')}{OLLAMA_API_CHAT_PATH}"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }

    backoff = BACKOFF_BASE_SECONDS
    for attempt in range(1, max_conn_retries + 1):
        try:
            with requests.post(
                url, json=payload, stream=True,
                timeout=(connect_timeout, read_timeout),
            ) as resp:
                if resp.status_code == 404:
                    raise OllamaError(
                        f"Model '{model}' was not found on the Ollama server.\n"
                        f"  -> Run: ollama pull {model}"
                    )
                resp.raise_for_status()

                content_parts: List[str] = []
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "error" in obj:
                        raise OllamaError(
                            f"Ollama returned an error: {obj['error']}"
                        )
                    piece = obj.get("message", {}).get("content", "")
                    if piece:
                        content_parts.append(piece)
                    if obj.get("done"):
                        break
                return "".join(content_parts)

        except OllamaError:
            raise
        except requests.exceptions.ConnectionError as exc:
            if attempt >= max_conn_retries:
                raise OllamaError(
                    f"Could not reach Ollama at {url} after {attempt} attempt(s).\n"
                    f"  -> Is Ollama installed and running? Try: ollama serve\n"
                    f"  -> Is the model pulled? Try: ollama pull {model}\n"
                    f"  Details: {exc}"
                ) from exc
            print(
                f"   (connection issue, retrying in {backoff}s -- "
                f"attempt {attempt}/{max_conn_retries})"
            )
            time.sleep(backoff)
            backoff *= 2

        except requests.exceptions.Timeout:
            if attempt >= max_conn_retries:
                raise OllamaError(
                    f"Ollama produced no output for {read_timeout}s between tokens, "
                    f"after {attempt} attempt(s).\n"
                    f"  -> The model may be too large/slow. Try a smaller model "
                    f"(e.g. llama3.2:3b or qwen2.5-coder:1.5b).\n"
                    f"  -> Or increase --read-timeout.\n"
                    f"  -> Run `ollama ps` to confirm the model is loaded."
                ) from None
            print(
                f"   (read timeout, retrying in {backoff}s -- "
                f"attempt {attempt}/{max_conn_retries})"
            )
            time.sleep(backoff)
            backoff *= 2

        except requests.exceptions.HTTPError as exc:
            raise OllamaError(f"Ollama returned HTTP error: {exc}") from exc

    raise OllamaError("Exhausted retries calling Ollama.")
