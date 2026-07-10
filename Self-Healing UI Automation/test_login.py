"""
test_login.py

Demonstrates self-healing locators end to end.

The locators below (BROKEN_*) intentionally match an OLDER version of
test_page.html. The actual page has since been redesigned with different
ids (see the comment in test_page.html). Instead of failing with
NoSuchElementException, SelfHealingDriver catches that, asks a local
Ollama model to find the equivalent element in the current DOM, and the
test proceeds normally.

Run:
    python test_login.py
"""

import os
import sys
import time

# Force UTF-8 stdout/stderr on Windows to avoid cp1252 codec errors
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from self_healing_driver import SelfHealingDriver, LocatorHealingError

# --- Deliberately broken locators (as if written against an old page version) ---
BROKEN_EMAIL_LOCATOR = ("id", "username")      # actual page now uses id="user_email"
BROKEN_PASSWORD_LOCATOR = ("id", "password")   # actual page now uses id="user_pwd"
BROKEN_BUTTON_LOCATOR = ("id", "login-btn")    # actual page now uses id="btn-submit-login"

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")


def run_test():
    options = Options()
    # Run headlessly for CI / non-GUI environments
    options.add_argument("--headless=new")

    driver = webdriver.Chrome(options=options)
    healing = SelfHealingDriver(driver, model=OLLAMA_MODEL)

    try:
        page_path = os.path.abspath("test_page.html")
        driver.get(f"file://{page_path}")

        email_field = healing.find_element(
            *BROKEN_EMAIL_LOCATOR, description="the email/username input field for login"
        )
        email_field.send_keys("tester@example.com")

        password_field = healing.find_element(
            *BROKEN_PASSWORD_LOCATOR, description="the password input field for login"
        )
        password_field.send_keys("hunter2")

        login_button = healing.find_element(
            *BROKEN_BUTTON_LOCATOR, description="the submit/login button"
        )
        login_button.click()

        time.sleep(0.5)  # let the page's JS update the result text
        result = driver.find_element("id", "result").text
        assert result == "Login Successful", f"Unexpected result: '{result}'"

        print("\nTEST PASSED - login flow completed despite broken locators.")

    except LocatorHealingError as e:
        print(f"\nTEST FAILED - could not self-heal: {e}")
        raise
    finally:
        driver.quit()


if __name__ == "__main__":
    run_test()
