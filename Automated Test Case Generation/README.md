# Automated Test Case Generation (Local LLM, Free)

Generates a comprehensive PyTest suite — happy path, boundary values,
edge cases, error handling — from a user story or acceptance criteria
document, using a locally running **Ollama** model. No API keys, no cost,
nothing leaves your machine.

## Files

| File | Purpose |
|---|---|
| `generate_tests.py` | The main script |
| `requirements.txt` | Python dependencies |
| `sample_user_story.md` | Small example input (single-shot mode) |
| `sample_user_story_large.md` | 30-criteria example input (auto-batch mode) |
| `solution_example_login.py` | Worked reference implementation making a real generated login test suite pass 16/16 — see "ModuleNotFoundError" section below |

## Step 1 — Install Ollama

Download and install from **https://ollama.com/download** (Windows, macOS, Linux).

Verify it's running:
```bash
ollama --version
```

## Step 2 — Pull a model

Any chat model works, but a **code-focused** model gives noticeably better
test code:

```bash
ollama pull qwen2.5-coder:7b     # recommended — strong at code, fits on most laptops
# or
ollama pull deepseek-coder-v2    # also strong at code, larger
# or
ollama pull llama3.1:8b          # solid general-purpose fallback
```

Ollama usually starts its server automatically after install. If not:
```bash
ollama serve
```
It listens on `http://localhost:11434` by default.

## Step 3 — Install Python dependencies

```bash
pip install -r requirements.txt
```

## Step 4 — Run it on the sample story

```bash
python generate_tests.py -i sample_user_story.md -o test_generated.py -m qwen2.5-coder:7b --verify
```

This will:
1. Read `sample_user_story.md`.
2. Send it to your local model with a prompt engineered to apply Boundary
   Value Analysis, Equivalence Partitioning, happy-path, edge-case, and
   error-path coverage (see "How the prompt works" below).
3. Extract the generated code from the model's fenced ` ```python ` block.
4. Validate it's syntactically correct Python (`ast.parse`); if not, it
   automatically sends the error back to the model and asks for a fix
   (up to `--max-retries`, default 2).
5. Write the result to `test_generated.py`.
6. Print a quick summary (how many test functions, how many are boundary
   vs. edge vs. error tests, whether `parametrize` was used).
7. With `--verify`, run `pytest --collect-only` on the output so you can see
   immediately whether PyTest can parse and collect every test.

## Step 4b — Run it on a LARGE story (e.g. 20-30+ acceptance criteria)

A second sample, `sample_user_story_large.md`, is a 30-criteria international
money-transfer story — the kind of document that used to cause
`ERROR: Ollama request timed out` on local models. Try it the same way:

```bash
python generate_tests.py -i sample_user_story_large.md -o test_generated_large.py -m qwen2.5-coder:7b --verify
```

For stories with more than 10 numbered acceptance criteria, the script
**automatically switches to batch mode**: it splits the criteria into groups
(8 per batch by default), generates a test module per batch, and merges them
into one file using Python's `ast` module (so imports/constants are
de-duplicated and colliding test names are auto-renamed instead of silently
overwritten). You'll see progress printed per batch:

```
-> Story has 30 numbered acceptance criteria -> splitting into 4 batch(es) of up to 8 each.
-> batch 1/4: calling model...
-> batch 2/4: calling model...
-> batch 3/4: calling model...
-> batch 4/4: calling model...
-> Merging batches into a single test module...
```

Batch 1 establishes the assumed function/class signature (in its
`ASSUMPTIONS` docstring); every later batch is explicitly told to reuse that
same signature, so the merged suite stays internally consistent instead of
each batch inventing its own API.

## Step 5 — Point it at your own code

1. Open `test_generated.py` and read the **ASSUMPTIONS** docstring at the top
   — the model documents what function/class signature it assumed (e.g.
   `login_user(username: str, password: str) -> tuple[bool, str]`).
2. Either:
   - Write a `solution.py` in the same folder implementing that signature, or
   - Edit the `from solution import ...` line in the generated file to point
     at your real module.
3. Run the suite for real:
   ```bash
   pytest test_generated.py -v
   ```

### `ModuleNotFoundError: No module named 'solution'` — is this a bug?

**No — this is expected**, and it's the most common point of confusion.
`test_generated.py` is written to test *your* implementation, which the
script has no way to know in advance. The generated tests literally say
`from solution import login_user` because the model was told to assume that
import path. Until a `solution.py` exists next to the test file (or you
redirect the import), every test will fail this way — it has nothing to do
with the quality of the generated tests, and it isn't something the script
can silently work around, since it doesn't have your business logic.

Two ways to resolve it:

- **You already have an implementation.** Just edit the `from solution
  import ...` line(s) in the generated test file to import from your real
  module instead (e.g. `from auth import login_user`).
- **You don't have one yet.** Run the script with `--with-stub`:
  ```bash
  python generate_tests.py -i user_story.md -o test_generated.py --with-stub
  ```
  This makes one extra model call that reads your generated tests and writes
  a `*_stub.py` file defining every function/class the tests import, each
  with a body of `raise NotImplementedError(...)`. Rename it to `solution.py`
  and run pytest again: the `ModuleNotFoundError`s disappear, and instead
  every test fails with a clear `NotImplementedError`, telling you exactly
  what's left to build. Fill in the real logic function by function and
  watch tests turn green.

  `solution_example_login.py` in this folder is a worked example — a full
  reference implementation (not a stub) that makes all 16 tests in the
  original login-user story pass, if you want to see the end state.

## Step 6 — Use it on your own user stories

```bash
python generate_tests.py -i path/to/your_story.txt -o test_your_feature.py --verify
```

Works with plain `.txt` or `.md` files — just the raw text of your user
story or acceptance criteria.

## How the prompt works

The script uses a two-part prompt:

- **System prompt** — instructs the model to act as a senior SDET and
  explicitly apply Boundary Value Analysis (min / min-1 / min+1 / max / max-1
  / max+1), Equivalence Partitioning, happy-path coverage, edge cases (None,
  empty, whitespace, unicode, wrong type, oversized input), and error-path
  coverage (`pytest.raises`). It also enforces a strict output contract: only
  one fenced Python code block, nothing else, so the script can parse it
  reliably.
- **User prompt** — your raw user story / acceptance criteria text.

If the model doesn't give a valid function signature to test against, it's
instructed to infer a reasonable one and document it in an `ASSUMPTIONS`
docstring instead of guessing silently.

## Self-healing retries

Free local models occasionally emit code with a stray syntax error. Instead
of failing, the script parses the code with Python's `ast` module, and if
that fails, sends the exact error message back to the model and asks it to
fix it — up to `--max-retries` times (default 2) — before giving up and
writing the best-effort result with a warning.

## CLI options

```
-i, --input          Path to the user story file (required)
-o, --output         Output .py path (default: test_generated.py)
-m, --model          Ollama model name (default: llama3.1)
--host               Ollama server URL (default: http://localhost:11434)
--temperature        Sampling temperature (default: 0.2 — keep this low for
                     consistent, less "creative" test generation)

--connect-timeout    Seconds to wait for the initial connection (default: 10)
--read-timeout       Seconds of SILENCE allowed between streamed tokens before
                     it's treated as a stall (default: 60). Because responses
                     are streamed, this does NOT need to cover the whole
                     generation — only gaps between tokens.
--max-conn-retries   Retries (exponential backoff) on connection/timeout
                     errors before giving up (default: 3)

--num-ctx            Context window requested from Ollama (default: 8192).
                     Lower this if your machine runs low on memory.
--num-predict        Max tokens to generate; -1 = until natural stop (default: -1)

--max-retries        Self-healing retries PER BATCH on syntax errors (default: 2)

--batch-size         Acceptance criteria per batch in batch mode (default: 8)
--batch-threshold    Auto-switch to batch mode above this many numbered
                     acceptance criteria (default: 10)
--no-batch           Force single-shot generation even for large stories
--force-batch        Force batch mode even for small stories

--verify             Run `pytest --collect-only` on the output after writing it
--with-stub          Also generate a *_stub.py scaffold (every function raises
                     NotImplementedError) so tests are importable immediately;
                     see "ModuleNotFoundError" section above
--with-impl          EXPERIMENTAL: also have the model write a full working
                     implementation, then actually RUN the real tests against
                     it and auto-repair on real failures. See section below.
--impl-max-retries   Repair attempts for --with-impl based on real test
                     failures (default: 3)
```

## `--with-impl`: generating a full working implementation (experimental)

If you don't have an implementation yet and want the AI to attempt one
end-to-end, run:

```bash
python generate_tests.py -i user_story.md -o test_generated.py --with-impl
```

This does more than just ask the model to "write the code":

1. It generates the implementation from the **acceptance criteria directly**
   (not by reverse-engineering the test file), and explicitly instructs the
   model not to special-case the literal example values that happen to
   appear in the tests — e.g. it must implement a real password-complexity
   *rule*, not `if password == "P@ssw0rd": return True`.
2. It then **actually runs the real generated tests** against the
   implementation with `pytest`, in an isolated temp directory — it doesn't
   just trust the model's claim that the code is correct.
3. If any tests fail, the exact failing test names and assertion messages are
   sent back to the model, which is asked to fix the *implementation* (not
   the tests) — up to `--impl-max-retries` times (default 3).
4. The result is written next to your test file as `solution.py` — **unless
   a `solution.py` already exists there**, in which case it's written to
   `solution_ai_generated.py` instead so your real code is never overwritten.
5. Every generated implementation file starts with a warning banner marking
   it as AI-generated and experimental.

**Important caveats:**
- Passing the generated tests only shows the implementation matches the AI's
  own reading of the acceptance criteria — it is *not* proof of correctness
  against your real requirements, and it is not a substitute for code review.
- For anything security- or finance-sensitive (authentication, money
  movement, PII), treat this strictly as a first draft. Read it line by line
  before trusting it with anything real.
- Where an acceptance criterion implies a real external dependency (sending
  an OTP, calling a live exchange-rate API, a real database), the model is
  instructed to write a clearly-marked in-memory placeholder
  (`# TODO: replace with real ...`) rather than fake it — you'll need to wire
  up the real integration yourself.
- This is not batched the way test generation is (merging partial business
  logic safely is much harder than merging test functions), so very large
  stories may need a bigger `--num-ctx` or a more capable model to avoid
  truncation on the implementation call specifically.

## Troubleshooting: errors this script handles automatically

| Symptom | What the script now does |
|---|---|
| `Ollama request timed out` on a large/complex story | Responses are streamed rather than awaited all at once, so a slow-but-still-generating model no longer looks "timed out". Large stories (>10 acceptance criteria) are also automatically split into smaller batches, so no single call has to produce a huge response. |
| Model connection drops mid-request | Automatically retried up to `--max-conn-retries` times with exponential backoff (2s, 4s, 8s...) before failing. |
| Model goes silent for a long stretch (e.g. still loading into memory) | Same retry/backoff as above; the error message also suggests checking `ollama ps` and trying a smaller model. |
| Model name not found (typo, or not pulled yet) | Clear error telling you to run `ollama pull <model>`. |
| Generated code has a stray syntax error | The exact Python error is sent back to the model with a request to return a corrected, complete version — up to `--max-retries` times per batch. |
| Output gets cut off / truncated on a big story | `--num-ctx`/`--num-predict` are raised well above Ollama's defaults, and — more importantly — batching keeps each individual generation short enough that truncation is unlikely in the first place. |
| Two batches happen to generate a test with the same name, or both define the same constant | The AST-based merge step automatically renames the colliding function (e.g. `test_foo__b2`) rather than silently dropping one, and de-duplicates identical constants/imports. |

If you still hit a timeout after all this (e.g. on very constrained hardware),
try: a smaller/faster model (`ollama pull llama3.2:3b`), a smaller
`--batch-size` (e.g. `4`), or a higher `--read-timeout`.

## Tips

- **Bigger / code-tuned models = better tests.** `qwen2.5-coder:7b` or
  `deepseek-coder-v2` will reason about boundaries far more reliably than a
  small general chat model.
- **Keep temperature low** (0.1–0.3). Test generation benefits from
  determinism, not creativity.
- **Very long acceptance criteria documents** may need a bigger `--timeout`
  and a model with a larger context window.
- If `--verify` shows import errors for `solution`, that's expected until you
  either write the real implementation or point the import at it — it's not
  a bug in the generated tests.