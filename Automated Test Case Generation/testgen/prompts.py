"""
testgen/prompts.py
==================
LLM prompt templates for the Automated Test Case Generation package.

All prompt text is centralised here so that prompt-engineering changes
can be made in one place without touching the generation or CLI logic.

Exported names
--------------
SYSTEM_PROMPT           — Main system prompt for the model acting as senior SDET
BATCH_SYSTEM_ADDENDUM   — Appended to SYSTEM_PROMPT in batch mode (batches 2+)
STUB_SYSTEM_PROMPT      — System prompt for generating a minimal solution stub
build_user_prompt()     — Wraps raw user-story text into the user-turn message
build_batch_prompt()    — Builds the user-turn message for a non-first batch
build_fix_prompt()      — Asks the model to fix a previously generated syntax error
build_stub_prompt()     — Asks the model to produce a solution.py stub from tests
"""

import textwrap


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT: str = textwrap.dedent("""\
    You are a senior SDET (Software Development Engineer in Test) who specializes
    in requirements-based test design, Boundary Value Analysis (BVA), and
    Equivalence Partitioning.

    You will be given a USER STORY or ACCEPTANCE CRITERIA (or a subset of one).
    Produce a single, complete, syntactically valid PyTest test module that
    comprehensively tests the described behavior.

    METHODOLOGY (apply all of these):
    1. Extract every explicit and implicit input, precondition, and business rule.
    2. For every bounded/numeric/length-constrained input, apply Boundary Value
       Analysis: test min, min-1, min+1, max, max-1, max+1, and a typical
       interior value.
    3. For every categorical or string input, apply Equivalence Partitioning:
       one test per valid class and one per distinct invalid class.
    4. Cover a happy-path test for every acceptance criterion.
    5. Cover edge cases: None/null, empty string, whitespace-only, duplicate
       entries, unicode/special characters, very large input, wrong type,
       missing required field, timing/race conditions if implied (e.g. retries,
       duplicate submissions, expiry windows).
    6. Cover error/negative paths: anything the requirements say should raise
       an exception, return an error, or be rejected -> use pytest.raises or
       assert on the error behavior.
    7. If the requirements do not give an exact function/class signature, infer
       a clean, reasonable one from the domain language used, and record it in
       an "ASSUMPTIONS" docstring at the top of the file.
    8. Use mocking (unittest.mock / pytest fixtures / monkeypatch) for anything
       that implies an external dependency (exchange-rate lookups, OTP delivery,
       clocks/timestamps, network calls) rather than assuming a real network
       call happens in the test.

    OUTPUT FORMAT (strict):
    - Output ONLY one fenced Python code block: ```python ... ``` -- nothing
      before or after it.
    - Start the file with a module docstring containing an "ASSUMPTIONS:"
      section describing the inferred function/class signature(s) under test.
    - Assume the code under test is importable as: from solution import *
    - Group tests with clear comments: "# --- Happy path ---",
      "# --- Boundary value analysis ---", "# --- Edge cases ---",
      "# --- Error handling ---"
    - Use pytest.mark.parametrize for boundary-value tables instead of
      duplicating near-identical test functions.
    - Give every test function a descriptive, GLOBALLY UNIQUE name across the
      whole suite, e.g. test_transfer_amount_rejects_value_below_minimum_boundary
      (this matters because this suite may be generated in multiple batches
      that get merged together -- avoid generic names like test_case_1).
    - Do not invent acceptance criteria that aren't implied by the input, but
      DO apply standard BVA / edge-case practice on top of what's given.
""")
"""
Main system prompt that instruct the model to act as a senior SDET
and apply BVA, EP, happy-path, edge-case, and error-path coverage.
The output format contract (fenced code block only) is strictly enforced.
"""

BATCH_SYSTEM_ADDENDUM: str = textwrap.dedent("""\

    IMPORTANT -- BATCH MODE:
    This large user story is being processed in multiple batches, one group of
    acceptance criteria at a time, and all batches will be merged into a single
    test file afterward. For this batch:
    - Do NOT repeat the module-level docstring/ASSUMPTIONS block -- that was
      already established in batch 1 (repeated below for your reference only;
      do not re-emit it).
    - Reuse the EXACT SAME function/class names and signatures already assumed
      in batch 1 -- do not invent a different API for the same feature.
    - Still include any `import` lines your batch's tests need (duplicates
      across batches will be automatically de-duplicated during merge).
    - Only write test functions for the acceptance criteria given in THIS batch.
    - Test function names must be unique across the whole suite -- prefix or
      describe them specifically enough that they won't collide with another
      batch's tests (e.g. include the rule number or topic in the name).
""")
"""
Appended to SYSTEM_PROMPT for batches 2 and beyond.
Instructs the model not to re-emit the ASSUMPTIONS block and to reuse the
API signature established by batch 1.
"""

STUB_SYSTEM_PROMPT: str = textwrap.dedent("""\
    You are a senior Python engineer. You will be given a complete PyTest test
    module. Your job is to generate ONLY a minimal stub implementation module
    (conventionally named solution.py) that makes the tests IMPORTABLE and
    COLLECTIBLE -- not correct.

    Rules:
    - Identify every name imported via `from solution import ...` (or
      `import solution`) across the test file, including any name referenced
      indirectly (e.g. via `patch('solution.some_helper', ...)`).
    - Define each as a function/class with a signature matching how it's
      CALLED in the tests (correct number/names of positional and keyword
      parameters, matching any default values implied by optional-looking
      calls).
    - Every function body must be exactly: `raise NotImplementedError("TODO: implement <name>")`
      -- do NOT attempt to implement the real business logic, even if it looks
      obvious from the test assertions. This is scaffolding only, so the
      developer fills in real logic themselves and the tests fail with clear
      assertion errors instead of import errors.
    - If a helper is only ever referenced via `unittest.mock.patch(...)` (never
      directly called in a way that reveals its signature), still define it
      with a reasonable signature (e.g. `(*args, **kwargs)`), since it must
      exist as an attribute on the module for `patch` to succeed.
    - Output ONLY one fenced Python code block (```python ... ```), nothing else.
""")
"""
System prompt used when generating a minimal solution.py stub.
The stub makes tests importable (raises NotImplementedError) so developers
can run the suite and see which functions they still need to implement.
"""


# ---------------------------------------------------------------------------
# User-turn prompt builders
# ---------------------------------------------------------------------------

def build_user_prompt(story_text: str) -> str:
    """
    Wrap raw user-story / acceptance-criteria text into the user-turn message.

    Args:
        story_text: The full content of the user story or acceptance criteria
                    document as a plain string.

    Returns:
        A formatted string ready to be sent as the user message to the model.
    """
    return f"USER STORY / ACCEPTANCE CRITERIA:\n\n{story_text.strip()}\n"


def build_batch_prompt(preamble: str, assumptions: str, batch_text: str,
                       batch_idx: int, total_batches: int) -> str:
    """
    Build the user-turn message for a non-first batch in batch mode.

    Args:
        preamble:       Story text before the first numbered acceptance criterion
                        (provides background context without being re-tested).
        assumptions:    ASSUMPTIONS docstring extracted from batch 1's output,
                        used to keep later batches API-consistent.
        batch_text:     The acceptance-criteria text for *this* batch only.
        batch_idx:      1-based index of the current batch.
        total_batches:  Total number of batches in this run.

    Returns:
        A formatted user-turn string for the LLM.
    """
    assumptions_block = assumptions or "(not captured -- infer a sensible consistent API)"
    return textwrap.dedent(f"""\
        BATCH {batch_idx} of {total_batches}

        Overall story context (for background only, already covered by earlier
        batches -- do not re-test items not listed below):
        {preamble.strip()}

        Assumed API from batch 1 (REUSE THIS, do not redefine):
        {assumptions_block}

        Acceptance criteria to cover IN THIS BATCH ONLY:
        {batch_text.strip()}
    """)


def build_fix_prompt(broken_code: str, error: str) -> str:
    """
    Ask the model to fix a previously generated code block that has a syntax error.

    Args:
        broken_code: The Python code string that failed ast.parse().
        error:       The SyntaxError message string (includes line/col info).

    Returns:
        A user-turn string asking the model to return a corrected version.
    """
    return textwrap.dedent(f"""\
        The Python test code you produced has a syntax error and failed to parse.

        SYNTAX ERROR:
        {error}

        PREVIOUS CODE:
        ```python
        {broken_code}
        ```

        Return a corrected, COMPLETE version (do not truncate). Output ONLY the
        fixed Python code in a single ```python fenced block, following the same
        OUTPUT FORMAT rules as before. Do not add commentary.
    """)


def build_stub_prompt(test_code: str) -> str:
    """
    Ask the model for a minimal solution.py scaffold that matches the test suite.

    Args:
        test_code: The full content of the generated PyTest module.

    Returns:
        A user-turn string instructing the model to produce a stub solution.
    """
    return textwrap.dedent(f"""\
        TEST MODULE:
        ```python
        {test_code}
        ```

        Generate the minimal solution.py stub described in your instructions.
    """)
