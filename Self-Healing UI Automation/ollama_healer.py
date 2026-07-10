"""
ollama_healer.py

Handles the "AI" side of self-healing locators:
  1. Simplify a raw HTML page source into a compact JSON list of interactive
     elements (so we don't blow past the local model's context window).
  2. Build a prompt describing the broken locator + that simplified DOM.
  3. Call a local Ollama model and parse its JSON reply into a new locator.

Requires Ollama running locally (default http://localhost:11434) with a model
already pulled, e.g.:
    ollama pull llama3.2
"""

import json
import re
import requests
from bs4 import BeautifulSoup

OLLAMA_URL = "http://localhost:11434/api/generate"

# Tags worth showing the model - anything a test is likely to locate.
INTERACTIVE_TAGS = ["input", "button", "a", "select", "textarea", "label", "form", "option"]

# Attributes worth showing the model - enough to build id/name/css/xpath locators.
RELEVANT_ATTRS = (
    "id", "name", "class", "type", "placeholder", "value",
    "role", "aria-label", "href", "for", "data-testid",
)

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
 "reasoning": "<one short sentence explaining the match>"}
"""


def simplify_dom(html: str, max_chars: int = 6000) -> str:
    """Strip an HTML page down to a compact JSON description of interactive elements."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "svg", "noscript"]):
        tag.decompose()

    elements = []
    for tag in soup.find_all(INTERACTIVE_TAGS):
        attrs = {k: v for k, v in tag.attrs.items() if k in RELEVANT_ATTRS}
        text = tag.get_text(strip=True)[:60]
        if not attrs and not text:
            continue
        elements.append({"tag": tag.name, "attrs": attrs, "text": text})

    snippet = json.dumps(elements)
    return snippet[:max_chars]


def build_prompt(old_by: str, old_value: str, description: str, dom_snippet: str,
                  previous_attempt: dict | None = None) -> str:
    extra = ""
    if previous_attempt:
        extra = (
            f"\nNote: you previously suggested by=\"{previous_attempt['by']}\", "
            f"value=\"{previous_attempt['value']}\" and that ALSO did not match any "
            "element. Pick a different element/locator this time.\n"
        )
    return f"""Broken locator: strategy="{old_by}", value="{old_value}"
Element purpose/description: {description or "unknown - infer from context"}
{extra}
Current DOM interactive elements (JSON array):
{dom_snippet}

Return the healed locator JSON now.
"""


def _extract_json(text: str) -> dict:
    """Ollama with format=json should return clean JSON, but be defensive anyway."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"Model did not return parseable JSON:\n{text}")


def ask_model_for_locator(old_by: str, old_value: str, description: str, html: str,
                           model: str = "llama3.2",
                           previous_attempt: dict | None = None,
                           timeout: int = 60) -> dict:
    """Query Ollama for a replacement locator. Returns dict with by/value/confidence/reasoning."""
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
