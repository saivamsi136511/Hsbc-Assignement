"""
ollama_healer.py
================
Ollama LLM backend for AI-powered locator healing.

Handles the AI side of self-healing locator suggestions in three steps:

1. **DOM simplification** — Strips a raw HTML page source down to a compact
   JSON array of interactive elements (inputs, buttons, links, etc.) so the
   prompt stays within the local model's context window.

2. **Prompt construction** — Combines the broken locator, the element
   description, the simplified DOM, and any previous failed attempt into a
   structured natural-language prompt.

3. **Model query + response parsing** — POSTs to the local Ollama ``/api/generate``
   endpoint, requests JSON output, and defensively parses the response into a
   ``{"by", "value", "confidence", "reasoning"}`` dict.

Requires Ollama running locally (default http://localhost:11434) with a model
already pulled, e.g.::

    ollama serve
    ollama pull llama3.1
"""

import json
import re
import requests
from bs4 import BeautifulSoup

from constants import (
    OLLAMA_BASE_URL,
    OLLAMA_API_GENERATE_PATH,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_TIMEOUT,
    LLM_TEMPERATURE,
    INTERACTIVE_TAGS,
    RELEVANT_ATTRS,
    DOM_MAX_CHARS,
    ELEMENT_TEXT_MAX_CHARS,
    TAGS_TO_REMOVE,
)

OLLAMA_URL = f"{OLLAMA_BASE_URL}{OLLAMA_API_GENERATE_PATH}"

SYSTEM_PROMPT = """You are an expert Selenium test automation engineer.
A test used a locator that no longer matches any element on the page because the
DOM changed (e.g. an id was renamed during a refactor).

You will be given:
1. The broken locator (strategy + value)
2. A description of what the element is supposed to do
3. A simplified JSON list of interactive elements currently in the DOM

Find the single best matching element and return a NEW locator for it.

Respond with ONLY a JSON object, no extra commentary, in exactly this schema:
{"by": "id" | "name" | "css" | "xpath" | "link_text" | "class_name",
 "value": "<the locator value>",
 "confidence": <float between 0 and 1>,
 "reasoning": "<one short sentence explaining the match>"}"""


def simplify_dom(html: str, max_chars: int = DOM_MAX_CHARS) -> str:
    """
    Reduce a full HTML page source to a compact JSON list of interactive elements.

    Strips non-interactive tags (scripts, styles, SVGs), then collects every
    element matching ``INTERACTIVE_TAGS`` along with its key attributes and
    visible text.  The result is JSON-serialised and truncated to ``max_chars``
    to fit within the model's context window.

    Args:
        html:      Raw HTML string of the current page (from
                   ``driver.page_source``).
        max_chars: Maximum character length of the returned JSON string.
                   Defaults to ``DOM_MAX_CHARS`` (6,000).

    Returns:
        A JSON-serialised string representing a list of dicts, each with
        ``{"tag": ..., "attrs": {...}, "text": "..."}``.  Truncated if
        the page is very large.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(TAGS_TO_REMOVE):
        tag.decompose()

    elements = []
    for tag in soup.find_all(INTERACTIVE_TAGS):
        attrs = {k: v for k, v in tag.attrs.items() if k in RELEVANT_ATTRS}
        text = tag.get_text(strip=True)[:ELEMENT_TEXT_MAX_CHARS]
        if not attrs and not text:
            continue
        elements.append({"tag": tag.name, "attrs": attrs, "text": text})

    snippet = json.dumps(elements)
    return snippet[:max_chars]


def build_prompt(
    old_by: str,
    old_value: str,
    description: str,
    dom_snippet: str,
    previous_attempt: dict | None = None,
) -> str:
    """
    Construct the user-turn prompt for a locator healing request.

    Includes the broken locator details, element purpose description, the
    simplified DOM snapshot, and (if applicable) a note about the previously
    suggested locator that also failed — so the model avoids repeating it.

    Args:
        old_by:           Original broken locator strategy string (e.g. ``"id"``)
        old_value:        Original broken locator value (e.g. ``"username"``)
        description:      Plain-English description of the element's purpose
                          (e.g. ``"the email input field for login"``).
                          If empty, the model infers from context.
        dom_snippet:      Compact JSON string from ``simplify_dom()``.
        previous_attempt: Dict with ``{"by": ..., "value": ...}`` for a
                          locator suggestion that was just tried and failed.
                          ``None`` on the first attempt.

    Returns:
        A formatted multi-line string ready to send as the user message.
    """
    extra = ""
    if previous_attempt:
        extra = (
            f"\nNote: you previously suggested by=\"{previous_attempt['by']}\", "
            f"value=\"{previous_attempt['value']}\" and that ALSO did not match any "
            "element. Pick a different element/locator this time.\n"
        )
    return (
        f'Broken locator: strategy="{old_by}", value="{old_value}"\n'
        f"Element purpose/description: {description or 'unknown - infer from context'}\n"
        f"{extra}\n"
        f"Current DOM interactive elements (JSON array):\n{dom_snippet}\n\n"
        "Return the healed locator JSON now.\n"
    )


def _extract_json(text: str) -> dict:
    """
    Defensively parse a JSON response from the Ollama model.

    Ollama's ``format=json`` option should return clean JSON, but
    models sometimes prefix/suffix the object with extra whitespace
    or even stray markdown.  This function tries three strategies:

    1. Parse the raw text directly.
    2. Extract the first ``{...}`` block with a regex and parse that.
    3. Raise ``ValueError`` if both fail.

    Args:
        text: Raw string response from the Ollama model.

    Returns:
        Parsed JSON as a dict.

    Raises:
        ValueError: If no valid JSON object can be extracted.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"Model did not return parseable JSON:\n{text}")


def ask_model_for_locator(
    old_by: str,
    old_value: str,
    description: str,
    html: str,
    model: str = DEFAULT_OLLAMA_MODEL,
    previous_attempt: dict | None = None,
    timeout: int = DEFAULT_OLLAMA_TIMEOUT,
) -> dict:
    """
    Query the local Ollama model for a replacement Selenium locator.

    Orchestrates the full healing pipeline for a single attempt:
    1. Calls ``simplify_dom()`` to produce a compact DOM JSON string.
    2. Calls ``build_prompt()`` to assemble the user-turn message.
    3. POSTs to the Ollama ``/api/generate`` endpoint with ``format=json``.
    4. Parses and validates the JSON response.

    Args:
        old_by:           The broken locator strategy (e.g. ``"id"``).
        old_value:        The broken locator value (e.g. ``"username"``).
        description:      Plain-English description of the element's purpose.
        html:             Current page source HTML (from ``driver.page_source``).
        model:            Ollama model name.  Defaults to ``DEFAULT_OLLAMA_MODEL``.
        previous_attempt: A ``{"by": ..., "value": ...}`` dict from the last
                          failed suggestion, to avoid repetition. ``None`` for
                          the first attempt.
        timeout:          HTTP request timeout in seconds.

    Returns:
        A dict with keys:
        - ``"by"``          — locator strategy string
        - ``"value"``       — locator value string
        - ``"confidence"``  — float 0.0–1.0 (self-reported by model)
        - ``"reasoning"``   — one-sentence explanation from the model

    Raises:
        RuntimeError: If the Ollama server is unreachable.
        ValueError:   If the model's response cannot be parsed as JSON.
    """
    dom_snippet = simplify_dom(html)
    prompt = build_prompt(old_by, old_value, description, dom_snippet, previous_attempt)

    payload = {
        "model": model,
        "system": SYSTEM_PROMPT,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.2},
    }

    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            "Could not reach Ollama at http://localhost:11434 - "
            "is 'ollama serve' running and is the model pulled? "
            f"(ollama pull {model})"
        ) from e

    data = resp.json()
    raw = data.get("response", "")
    parsed = _extract_json(raw)

    for key in ("by", "value"):
        if key not in parsed:
            raise ValueError(f"Model response missing '{key}': {parsed}")
    parsed.setdefault("confidence", 0.0)
    parsed.setdefault("reasoning", "")
    return parsed
