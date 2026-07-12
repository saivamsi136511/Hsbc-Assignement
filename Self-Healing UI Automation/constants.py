"""
constants.py
============
Centralized constants for the Self-Healing UI Automation project.

All magic strings, numeric defaults, and configuration values used by
self_healing_driver.py and ollama_healer.py are defined here so they
can be changed in one place without hunting through the codebase.
"""

from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Ollama server defaults
# ---------------------------------------------------------------------------

OLLAMA_BASE_URL: str = "http://localhost:11434"
"""Base URL for the locally running Ollama server."""

OLLAMA_API_GENERATE_PATH: str = "/api/generate"
"""REST path for Ollama's text generation endpoint."""

DEFAULT_OLLAMA_MODEL: str = "llama3.1"
"""
Default Ollama model used for locator healing suggestions.
Smaller / faster models (e.g. llama3.2:3b) work well for compact DOM inputs.
"""

DEFAULT_OLLAMA_TIMEOUT: int = 180
"""Seconds to wait for an Ollama response before timing out."""

LLM_TEMPERATURE: float = 0.2
"""Sampling temperature for the LLM. Low = more deterministic locator suggestions."""

# ---------------------------------------------------------------------------
# Healing behaviour
# ---------------------------------------------------------------------------

MAX_HEAL_ATTEMPTS: int = 2
"""
Maximum number of AI-suggested locators to try before raising
LocatorHealingError and failing the test step.
"""

LOG_FILE_NAME: str = "healed_locators.json"
"""
Filename (relative to the script directory) for the audit log of every
successful locator heal. Used to generate suggested code fixes for humans.
"""

# ---------------------------------------------------------------------------
# DOM simplification
# ---------------------------------------------------------------------------

INTERACTIVE_TAGS: List[str] = [
    "input", "button", "a", "select", "textarea", "label", "form", "option"
]
"""
HTML tags included in the simplified DOM snapshot sent to the AI model.
Only elements a test is likely to locate are included to keep the prompt compact.
"""

RELEVANT_ATTRS: Tuple[str, ...] = (
    "id", "name", "class", "type", "placeholder", "value",
    "role", "aria-label", "href", "for", "data-testid",
)
"""
Element attributes retained in the simplified DOM JSON.
These provide enough information to construct id/name/css/xpath locators.
"""

DOM_MAX_CHARS: int = 6_000
"""
Maximum character length of the simplified DOM JSON sent to the model.
Truncating large pages keeps the prompt within the model's context window.
"""

ELEMENT_TEXT_MAX_CHARS: int = 60
"""Maximum characters of visible element text included in the DOM snapshot."""

TAGS_TO_REMOVE: List[str] = ["script", "style", "svg", "noscript"]
"""HTML tags stripped from the page source before building the DOM snapshot."""

# ---------------------------------------------------------------------------
# Selenium locator strategy mapping
# ---------------------------------------------------------------------------

# Maps plain-string strategy names (used in the AI prompt schema) to
# Selenium By constants. By constants are imported at runtime to avoid
# making selenium a hard import of this constants module.
BY_STRATEGY_NAMES: Tuple[str, ...] = (
    "id", "name", "css", "xpath", "link_text", "class_name"
)
"""
All locator strategy names accepted by the SelfHealingDriver and the AI prompt.
The AI model is instructed to return one of these in its JSON response.
"""

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_PREFIX: str = "[self-heal]"
"""Console log prefix prepended to all self-healing diagnostic messages."""

TIMESTAMP_FORMAT: str = "%Y-%m-%d %H:%M:%S"
"""strftime format used for timestamps in the healed_locators.json audit log."""
