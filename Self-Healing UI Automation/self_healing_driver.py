"""
self_healing_driver.py
======================
Selenium WebDriver proxy with AI-powered self-healing locators.

Wraps a standard Selenium ``WebDriver`` so that ``find_element()`` calls
automatically recover from ``NoSuchElementException`` by consulting a local
Ollama language model.  When a locator fails, the model receives:
- The original broken locator strategy and value
- A compact JSON snapshot of interactive elements in the live DOM
- An optional plain-English description of what the element is supposed to do

The model suggests a replacement locator, which is tried immediately.  If it
also fails the model is told about the failed attempt and asked to try a
different approach — up to ``MAX_HEAL_ATTEMPTS`` times (default: 2).

Every successful heal is:
1. **Cached** in-memory for the lifetime of the driver session, so re-locating
   the same element later in the same test does not incur another model call.
2. **Logged** to ``healed_locators.json`` with a ready-to-paste code suggestion,
   creating an audit trail that developers can use to fix the underlying tests.

Usage
-----
    from selenium import webdriver
    from self_healing_driver import SelfHealingDriver

    driver = webdriver.Chrome()
    healing = SelfHealingDriver(driver, model="llama3.1")

    el = healing.find_element("id", "username", description="email/login field")
    el.send_keys("someone@example.com")
"""

import json
import time
from pathlib import Path

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from constants import (
    MAX_HEAL_ATTEMPTS,
    LOG_FILE_NAME,
    BY_STRATEGY_NAMES,
    LOG_PREFIX,
    TIMESTAMP_FORMAT,
)
from ollama_healer import ask_model_for_locator


# ---------------------------------------------------------------------------
# Locator strategy mapping
# ---------------------------------------------------------------------------

BY_MAP = {
    "id":         By.ID,
    "name":       By.NAME,
    "css":        By.CSS_SELECTOR,
    "xpath":      By.XPATH,
    "link_text":  By.LINK_TEXT,
    "class_name": By.CLASS_NAME,
}
"""
Maps plain-string locator strategy names (used in the AI prompt and audit log)
to Selenium ``By`` constants.  Only strategies in this map are accepted by
``find_element`` and returned by the AI model.
"""

LOG_FILE = Path(__file__).parent / LOG_FILE_NAME


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LocatorHealingError(Exception):
    """
    Raised when the AI model's suggested locator(s) also fail to find an element.

    This exception propagates to the test, causing it to fail with a clear
    message indicating that self-healing was attempted but unsuccessful.

    Check ``healed_locators.json`` for previously successful heals and
    ``ollama serve`` / ``ollama pull <model>`` if Ollama is unavailable.
    """


# ---------------------------------------------------------------------------
# Main driver proxy
# ---------------------------------------------------------------------------

class SelfHealingDriver:
    """
    A proxy around a Selenium ``WebDriver`` that intercepts ``NoSuchElementException``
    and uses a local Ollama model to suggest replacement locators.

    The driver is transparent for all element interactions other than
    ``find_element`` — calling code does not need to be restructured.

    Args:
        driver:  An already-constructed Selenium ``WebDriver`` instance.
        model:   Ollama model name to use for healing suggestions.
                 Defaults to ``"llama3.1"``.  A faster model (e.g.
                 ``"llama3.2:3b"``) may be preferable for CI environments.
        verbose: If ``True`` (default), prints ``[self-heal]``-prefixed
                 progress messages to stdout during healing attempts.

    Attributes:
        _cache: In-memory cache mapping ``(by, value)`` tuples to their
                last successfully healed ``(new_by, new_value)`` tuples.
                Persists only for the lifetime of this driver instance.
    """

    def __init__(self, driver, model: str = "llama3.1", verbose: bool = True) -> None:
        self.driver = driver
        self.model = model
        self.verbose = verbose
        # Cache: (by, value) -> (healed_by, healed_value)
        # Avoids re-querying the model for a locator we've already healed.
        self._cache: dict[tuple[str, str], tuple[str, str]] = {}

    def _log(self, msg: str) -> None:
        """
        Print a progress message to stdout when verbose mode is enabled.

        Args:
            msg: The message text (will be prefixed with ``[self-heal]``).

        Returns:
            None.
        """
        if self.verbose:
            print(f"{LOG_PREFIX} {msg}")

    def _record_healing(
        self,
        old_by: str,
        old_value: str,
        new_by: str,
        new_value: str,
        confidence: float,
        reasoning: str,
    ) -> None:
        """
        Append a record of a successful locator heal to the JSON audit log.

        The log entry includes a ready-to-paste code suggestion so that
        developers can update the test source to use the new locator directly,
        avoiding repeated self-healing overhead in subsequent runs.

        Args:
            old_by:     Original (broken) locator strategy string.
            old_value:  Original (broken) locator value.
            new_by:     Healed locator strategy string suggested by the model.
            new_value:  Healed locator value suggested by the model.
            confidence: Model's self-reported confidence (0.0–1.0).
            reasoning:  One-sentence explanation from the model.

        Returns:
            None. Side effect: appends to ``healed_locators.json``.
        """
        entry = {
            "timestamp":     time.strftime(TIMESTAMP_FORMAT),
            "old_locator":   {"by": old_by, "value": old_value},
            "new_locator":   {"by": new_by, "value": new_value},
            "confidence":    confidence,
            "reasoning":     reasoning,
            "suggested_code_fix": (
                f'By.{new_by.upper()}, "{new_value}"'
                f'  # was By.{old_by.upper()}, "{old_value}"'
            ),
        }
        history = []
        if LOG_FILE.exists():
            try:
                history = json.loads(LOG_FILE.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                history = []
        history.append(entry)
        LOG_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")

    def find_element(self, by: str, value: str, description: str = ""):
        """
        Drop-in replacement for ``driver.find_element(by, value)`` with AI healing.

        Accepts plain-string locator strategies (``"id"``, ``"name"``, ``"css"``,
        ``"xpath"``, ``"link_text"``, ``"class_name"``) instead of Selenium ``By``
        constants.  This keeps the strategy loggable, cacheable, and sendable
        to the Ollama model in the healing prompt.

        If the locator was previously healed in this session, the cached
        replacement is used directly without another model call.

        If the element is not found, the AI healing pipeline is triggered:
        1. The live page DOM is simplified to a compact JSON list.
        2. The model is asked to suggest a replacement locator.
        3. Up to ``MAX_HEAL_ATTEMPTS`` suggestions are tried.
        4. A successful heal is cached and logged.
        5. If all suggestions fail, ``LocatorHealingError`` is raised.

        Args:
            by:          Plain-string locator strategy. One of: ``"id"``,
                         ``"name"``, ``"css"``, ``"xpath"``, ``"link_text"``,
                         ``"class_name"``.
            value:       The locator value (e.g. ``"user_email"`` for by=``"id"``).
            description: Optional plain-English description of what the element
                         does (e.g. ``"the email input field for login"``).
                         Providing a good description significantly improves
                         healing accuracy.

        Returns:
            A Selenium ``WebElement`` — the same type returned by the
            underlying ``driver.find_element()``.

        Raises:
            LocatorHealingError: If the element cannot be found even after
                                 all self-healing attempts.
            KeyError:            If ``by`` is not one of the supported strategy
                                 names.
        """
        cache_key = (by, value)
        active_by, active_value = by, value

        if cache_key in self._cache:
            active_by, active_value = self._cache[cache_key]
            self._log(
                f"Using previously healed locator for {by}='{value}' -> "
                f"{active_by}='{active_value}'"
            )

        try:
            return self.driver.find_element(BY_MAP[active_by], active_value)
        except NoSuchElementException:
            self._log(
                f"Locator broken: by='{active_by}', value='{active_value}'. "
                f"Asking {self.model} to heal it..."
            )
            return self._heal_and_retry(by, value, description)

    def _heal_and_retry(self, by: str, value: str, description: str):
        """
        Core healing loop: query the model, try suggested locators, cache success.

        Iterates up to ``MAX_HEAL_ATTEMPTS`` times.  On each attempt, the model
        is called with the broken locator, the live DOM snapshot, and (if this
        is not the first attempt) the locator that was just tried and failed —
        so the model avoids suggesting the same locator twice.

        Args:
            by:          Original broken locator strategy string.
            value:       Original broken locator value.
            description: Plain-English description of the element's purpose.

        Returns:
            The located Selenium ``WebElement`` on the first successful heal.

        Raises:
            LocatorHealingError: If all suggestions fail, or if the model call
                                 itself throws an exception.
        """
        html = self.driver.page_source
        previous_attempt = None
        last_error = None

        for attempt in range(1, MAX_HEAL_ATTEMPTS + 1):
            try:
                suggestion = ask_model_for_locator(
                    old_by=by,
                    old_value=value,
                    description=description,
                    html=html,
                    model=self.model,
                    previous_attempt=previous_attempt,
                )
            except Exception as exc:
                raise LocatorHealingError(f"Model call failed: {exc}") from exc

            new_by = suggestion["by"]
            new_value = suggestion["value"]
            confidence = suggestion.get("confidence", 0.0)
            reasoning = suggestion.get("reasoning", "")

            if new_by not in BY_MAP:
                self._log(
                    f"Attempt {attempt}: model returned unknown strategy "
                    f"'{new_by}', skipping."
                )
                previous_attempt = {"by": new_by, "value": new_value}
                continue

            self._log(
                f"Attempt {attempt}: model suggests by='{new_by}', "
                f"value='{new_value}' (confidence={confidence:.2f}) — {reasoning}"
            )

            try:
                element = self.driver.find_element(BY_MAP[new_by], new_value)
            except NoSuchElementException as exc:
                last_error = exc
                previous_attempt = {"by": new_by, "value": new_value}
                self._log(
                    f"Attempt {attempt}: suggested locator also failed. Retrying..."
                )
                continue

            # Success: cache and record the heal for the developer's reference.
            self._cache[(by, value)] = (new_by, new_value)
            self._record_healing(by, value, new_by, new_value, confidence, reasoning)
            self._log(
                f"Healed successfully: {by}='{value}' -> {new_by}='{new_value}'. "
                f"Logged to {LOG_FILE.name}"
            )
            return element

        raise LocatorHealingError(
            f"Could not heal locator by='{by}', value='{value}' after "
            f"{MAX_HEAL_ATTEMPTS} attempts. Last error: {last_error}"
        )
