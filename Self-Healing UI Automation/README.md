# Self-Healing Selenium Test (powered by local Ollama)

Demonstrates a resilient test architecture: locators are deliberately broken
(simulating a UI redesign), and instead of the test failing with
`NoSuchElementException`, a local LLM (via Ollama) looks at the live DOM and
suggests a working replacement locator - which the test then uses to continue.

## How it works

```
test_login.py                  -- test with intentionally broken locators
      |
      v
self_healing_driver.py         -- wraps driver.find_element()
      |  catches NoSuchElementException
      v
ollama_healer.py                -- simplifies DOM -> prompt -> calls Ollama
      |
      v
Ollama (local, e.g. llama3.2)  -- returns {"by": "css", "value": "...", ...}
      |
      v
self_healing_driver.py         -- retries find_element with new locator,
                                   caches it, logs it to healed_locators.json
```

Key design points:
- **DOM simplification**: the full `page_source` is stripped down to just
  interactive elements (`input`, `button`, `a`, `select`, etc.) with their
  relevant attributes, as compact JSON. This keeps the prompt small enough
  for small/fast local models and avoids blowing past context limits.
- **Structured output**: the Ollama call uses `format: "json"` and a strict
  schema in the system prompt, so responses parse reliably.
- **Caching**: once a locator is healed, the new one is reused for the rest
  of the run instead of calling the model again.
- **Retry budget**: if the model's first suggestion also doesn't match
  anything, it gets one more attempt with the failed guess excluded.
- **Audit log**: every successful heal is appended to `healed_locators.json`
  with a suggested code diff, so a human can permanently fix the test source
  later. Self-healing should keep CI green today, not hide the drift forever.

## Setup

1. **Install Ollama** (macOS/Linux/Windows): https://ollama.com/download

2. **Pull a model** (small + fast is fine for this use case):
   ```bash
   ollama pull llama3.2
   ```
   Make sure Ollama is running (`ollama serve`, or just open the app).

3. **Install a Chrome/Chromium browser** if you don't already have one,
   plus a matching driver. `webdriver-manager` (included below) handles the
   driver download for you automatically.

4. **Install Python deps**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Run the test**:
   ```bash
   python test_login.py
   ```

   You should see output like:
   ```
   [self-heal] Locator broken: by='id', value='username'. Asking llama3.2 to heal it...
   [self-heal] Attempt 1: model suggests by='id', value='user_email' (confidence=0.95) - matches the email input by placeholder/type
   [self-heal] Healed successfully: id='username' -> id='user_email'. Logged to healed_locators.json

   TEST PASSED - login flow completed despite broken locators.
   ```

## Files

| File | Purpose |
|---|---|
| `test_page.html` | Sample "redesigned" page - ids no longer match the old test |
| `test_login.py` | The test itself, with deliberately broken locators |
| `self_healing_driver.py` | Wraps `find_element`, catches failures, retries with healed locator |
| `ollama_healer.py` | DOM simplification + prompt building + Ollama API call |
| `healed_locators.json` | Auto-generated audit log of every heal (created on first run) |

## Trying it yourself

Open `test_page.html`, rename an id or swap an element's tag, then re-run
`test_login.py` without changing anything in the test itself - the healer
should find the new element on its own. You can also point
`self_healing_driver.SelfHealingDriver` at a real webdriver session against
any site to try it beyond this toy example.

## Notes / limitations

- This heals **element-not-found** failures. It won't recover from a
  feature that was genuinely removed, or from timing/race issues (that's a
  job for explicit waits, not this).
- Model quality matters: `llama3.2` (3B) is fast and works for small pages
  like this demo; for larger/more ambiguous DOMs, try a bigger model, e.g.
  `ollama pull qwen2.5:7b` and set `OLLAMA_MODEL=qwen2.5:7b`.
- Treat the healed locator as a stopgap, not a fix - use
  `healed_locators.json`'s `suggested_code_fix` field to update your real
  test source so you're not paying the LLM-latency cost on every run.
