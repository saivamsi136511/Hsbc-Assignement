"""
self_healing_driver.py

Wraps a Selenium WebDriver so that find_element() calls automatically recover
from NoSuchElementException by asking a local Ollama model to suggest a
replacement locator based on the live DOM.

Usage:
    driver = webdriver.Chrome()
    healing_driver = SelfHealingDriver(driver, model="llama3.2")

    el = healing_driver.find_element(By.ID, "username", description="email/login field")
    el.send_keys("someone@example.com")
"""

import json
import time
from pathlib import Path

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from ollama_healer import ask_model_for_locator

BY_MAP = {
    "id": By.ID,
    "name": By.NAME,
    "css": By.CSS_SELECTOR,
    "xpath": By.XPATH,
    "link_text": By.LINK_TEXT,
    "class_name": By.CLASS_NAME,
}

MAX_HEAL_ATTEMPTS = 2  # how many different suggestions to try before giving up
LOG_FILE = Path(__file__).parent / "healed_locators.json"


class LocatorHealingError(Exception):
    """Raised when the model's suggested locator(s) also fail to find an element."""


class SelfHealingDriver:
    def __init__(self, driver, model: str = "llama3.2", verbose: bool = True):
        self.driver = driver
        self.model = model
        self.verbose = verbose
        # Cache: (by, value) -> (healed_by, healed_value). Avoids re-asking the
        # model for a locator we've already successfully healed this run.
        self._cache: dict[tuple[str, str], tuple[str, str]] = {}

    def _log(self, msg: str):
        if self.verbose:
            print(f"[self-heal] {msg}")

    def _record_healing(self, old_by, old_value, new_by, new_value, confidence, reasoning):
        """Append a record of the heal to a JSON log for audit / later code fixes."""
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "old_locator": {"by": old_by, "value": old_value},
            "new_locator": {"by": new_by, "value": new_value},
            "confidence": confidence,
            "reasoning": reasoning,
            "suggested_code_fix": f'By.{new_by.upper()}, "{new_value}"  # was By.{old_by.upper()}, "{old_value}"',
        }
        history = []
        if LOG_FILE.exists():
            try:
                history = json.loads(LOG_FILE.read_text())
            except json.JSONDecodeError:
                history = []
        history.append(entry)
        LOG_FILE.write_text(json.dumps(history, indent=2))

    def find_element(self, by: str, value: str, description: str = ""):
        """
        Drop-in replacement for driver.find_element(by, value).
        `by` should be one of: "id", "name", "css", "xpath", "link_text", "class_name"
        (plain strings, not selenium.webdriver.common.by.By constants) so the
        same string can be logged, cached, and sent to the model.
        """
        cache_key = (by, value)
        active_by, active_value = by, value

        if cache_key in self._cache:
            active_by, active_value = self._cache[cache_key]
            self._log(f"Using previously healed locator for {by}='{value}' -> "
                      f"{active_by}='{active_value}'")

        try:
            return self.driver.find_element(BY_MAP[active_by], active_value)
        except NoSuchElementException:
            self._log(f"Locator broken: by='{active_by}', value='{active_value}'. "
                      f"Asking {self.model} to heal it...")
            return self._heal_and_retry(by, value, description)

    def _heal_and_retry(self, by: str, value: str, description: str):
        html = self.driver.page_source
        previous_attempt = None
        last_error = None

        for attempt in range(1, MAX_HEAL_ATTEMPTS + 1):
            try:
                suggestion = ask_model_for_locator(
                    old_by=by, old_value=value, description=description,
                    html=html, model=self.model, previous_attempt=previous_attempt,
                )
            except Exception as e:
                raise LocatorHealingError(f"Model call failed: {e}") from e

            new_by = suggestion["by"]
            new_value = suggestion["value"]
            confidence = suggestion.get("confidence", 0.0)
            reasoning = suggestion.get("reasoning", "")

            if new_by not in BY_MAP:
                self._log(f"Attempt {attempt}: model returned unknown strategy "
                          f"'{new_by}', skipping.")
                previous_attempt = {"by": new_by, "value": new_value}
                continue

            self._log(f"Attempt {attempt}: model suggests by='{new_by}', "
                      f"value='{new_value}' (confidence={confidence:.2f}) - {reasoning}")

            try:
                element = self.driver.find_element(BY_MAP[new_by], new_value)
            except NoSuchElementException as e:
                last_error = e
                previous_attempt = {"by": new_by, "value": new_value}
                self._log(f"Attempt {attempt}: suggested locator also failed. Retrying...")
                continue

            # Success - cache it and log it for the human to eventually fix in source.
            self._cache[(by, value)] = (new_by, new_value)
            self._record_healing(by, value, new_by, new_value, confidence, reasoning)
            self._log(f"Healed successfully: {by}='{value}' -> {new_by}='{new_value}'. "
                      f"Logged to {LOG_FILE.name}")
            return element

        raise LocatorHealingError(
            f"Could not heal locator by='{by}', value='{value}' after "
            f"{MAX_HEAL_ATTEMPTS} attempts. Last error: {last_error}"
        )
