#!/usr/bin/env python3
"""
generate_tests.py
==================
Generates a comprehensive PyTest test suite (happy-path + boundary-value +
edge-case + error-path scenarios) from a user story / acceptance-criteria
document, using a locally running Ollama model. No API keys, no cost.

USAGE
-----
    python generate_tests.py -i user_story.md -o test_generated.py
    python generate_tests.py -i user_story.md -o test_generated.py -m qwen2.5-coder:7b --verify

For LARGE documents (many acceptance criteria), the script automatically
splits the story into batches, generates tests per batch, and merges them
into one file -- this avoids single-call timeouts/truncation on local models.

PREREQS
-------
    1. Install Ollama:   https://ollama.com/download
    2. Pull a model:     ollama pull qwen2.5-coder:7b   (or llama3.1, deepseek-coder-v2, ...)
    3. Start the server: ollama serve   (often already running as a background service)
    4. pip install -r requirements.txt
"""

import argparse
import ast
import json
import re
import sys
import textwrap
import time
from pathlib import Path

import requests


# --------------------------------------------------------------------------- #
# 1. PROMPT ENGINEERING
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = textwrap.dedent("""\
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

BATCH_SYSTEM_ADDENDUM = textwrap.dedent("""\

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

STUB_SYSTEM_PROMPT = textwrap.dedent("""\
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


def build_stub_prompt(test_code: str) -> str:
    return textwrap.dedent(f"""\
        TEST MODULE:
        ```python
        {test_code}
        ```

        Generate the minimal solution.py stub described in your instructions.
    """)


def build_user_prompt(story_text: str) -> str:
    return f"USER STORY / ACCEPTANCE CRITERIA:\n\n{story_text.strip()}\n"


def build_batch_prompt(preamble: str, assumptions: str, batch_text: str,
                        batch_idx: int, total_batches: int) -> str:
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


# --------------------------------------------------------------------------- #
# 2. SPLITTING A LARGE STORY INTO BATCHES
# --------------------------------------------------------------------------- #

NUMBERED_ITEM_RE = re.compile(r"^[ \t]*(\d{1,3})\.[ \t]+", re.MULTILINE)


def parse_acceptance_items(story_text: str):
    """
    Split the story into (preamble, [item_text, item_text, ...]) based on
    numbered acceptance criteria ("1. ...", "2. ..."). Each item_text includes
    any wrapped/continuation lines up to the next numbered item.
    Returns (preamble, []) if fewer than 2 numbered items are found (i.e. this
    story isn't in a numbered-list format we can safely split).
    """
    matches = list(NUMBERED_ITEM_RE.finditer(story_text))
    if len(matches) < 2:
        return story_text, []

    preamble = story_text[:matches[0].start()].strip()
    items = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(story_text)
        items.append(story_text[start:end].rstrip())
    return preamble, items


def chunk_items(items, batch_size):
    return [items[i:i + batch_size] for i in range(0, len(items), batch_size)]


def extract_assumptions(code: str) -> str:
    """Pull the module docstring (expected to contain ASSUMPTIONS) out of code."""
    try:
        tree = ast.parse(code)
        doc = ast.get_docstring(tree)
        return doc or ""
    except SyntaxError:
        return ""


def ensure_pytest_import(code: str) -> str:
    """Ensure pytest and solution imports are present when needed."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    # Python built-ins that should never be imported from solution
    BUILTINS = {
        'print', 'range', 'len', 'str', 'int', 'float', 'bool', 'dict', 'list',
        'set', 'tuple', 'isinstance', 'type', 'callable', 'sum', 'min', 'max',
        'sorted', 'reversed', 'enumerate', 'zip', 'map', 'filter', 'any', 'all',
        'open', 'input', 'format', 'abs', 'round', 'pow', 'divmod', 'hash',
        'hex', 'oct', 'bin', 'chr', 'ord', 'eval', 'exec', 'compile', 'vars',
        'dir', 'getattr', 'setattr', 'hasattr', 'delattr', 'property', 'classmethod',
        'staticmethod', 'super', 'object', 'Exception', 'BaseException', 'ValueError',
        'TypeError', 'KeyError', 'IndexError', 'AttributeError', 'IOError',
    }

    imports_needed = []
    
    # Check for pytest usage
    if "@pytest.mark" in code or "pytest." in code:
        if not re.search(r"^\s*(import pytest|from pytest\s+import\b)", code, re.MULTILINE):
            imports_needed.append("import pytest")
    
    # Check for function calls from solution module and extract function names
    solution_functions = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            func_name = node.func.id
            # Only add if NOT a built-in
            if func_name not in BUILTINS:
                solution_functions.add(func_name)
    
    # Add from solution import ... if functions are called but not imported
    if solution_functions:
        existing_imports = re.findall(r"from solution import ([^\n]+)", code)
        existing_names = set()
        for imp in existing_imports:
            existing_names.update(name.strip() for name in imp.split(','))
        
        missing = solution_functions - existing_names
        if missing:
            imports_needed.append(f"from solution import {', '.join(sorted(missing))}")
    
    if not imports_needed:
        return code
    
    # Insert imports after module docstring if present
    lines = code.splitlines()
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(
            tree.body[0].value, ast.Constant) and isinstance(
            tree.body[0].value.value, str):
        insert_at = tree.body[0].end_lineno
        lines = lines[:insert_at] + imports_needed + lines[insert_at:]
    else:
        lines = imports_needed + lines

    return "\n".join(lines) + ("\n" if code.endswith("\n") else "")


def write_stub_module(stub_code: str, output_path: Path) -> Path:
    """Write a stub module to an importable path for the generated tests."""
    preferred_path = output_path.with_name("solution.py")
    if preferred_path.exists():
        fallback_path = output_path.with_name("solution_stub.py")
        fallback_path.write_text(stub_code, encoding="utf-8")
        return fallback_path

    preferred_path.write_text(stub_code, encoding="utf-8")
    return preferred_path


# --------------------------------------------------------------------------- #
# 3. LLM CALL (Ollama, local, free) -- STREAMED with retry/backoff
# --------------------------------------------------------------------------- #

class OllamaError(RuntimeError):
    pass


def call_ollama(messages, model, host, temperature, num_ctx, num_predict,
                 connect_timeout, read_timeout, max_conn_retries):
    """
    Calls Ollama's /api/chat with stream=True and accumulates the full
    response. Streaming means we only need bytes to arrive within
    `read_timeout` seconds of EACH OTHER (i.e. the model must keep producing
    tokens), not within read_timeout for the ENTIRE generation -- this is what
    actually fixes false timeouts on long generations.

    Retries transient connection/timeout errors with exponential backoff
    before giving up.
    """
    url = f"{host.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }

    backoff = 2
    for attempt in range(1, max_conn_retries + 1):
        try:
            with requests.post(url, json=payload, stream=True,
                                timeout=(connect_timeout, read_timeout)) as resp:
                if resp.status_code == 404:
                    raise OllamaError(
                        f"Model '{model}' was not found on the Ollama server.\n"
                        f"  -> Run: ollama pull {model}"
                    )
                resp.raise_for_status()

                content_parts = []
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "error" in obj:
                        raise OllamaError(f"Ollama returned an error: {obj['error']}")
                    piece = obj.get("message", {}).get("content", "")
                    if piece:
                        content_parts.append(piece)
                    if obj.get("done"):
                        break
                return "".join(content_parts)

        except OllamaError:
            raise
        except requests.exceptions.ConnectionError as e:
            if attempt >= max_conn_retries:
                raise OllamaError(
                    f"Could not reach Ollama at {url} after {attempt} attempt(s).\n"
                    f"  -> Is Ollama installed and running? Try: ollama serve\n"
                    f"  -> Is the model pulled? Try: ollama pull {model}\n"
                    f"  Details: {e}"
                )
            print(f"   (connection issue, retrying in {backoff}s -- "
                  f"attempt {attempt}/{max_conn_retries})")
            time.sleep(backoff)
            backoff *= 2
        except requests.exceptions.Timeout:
            if attempt >= max_conn_retries:
                raise OllamaError(
                    f"Ollama produced no output for {read_timeout}s between tokens, "
                    f"after {attempt} attempt(s).\n"
                    f"  -> The model may be too large/slow for this machine. Try a "
                    f"smaller model (e.g. llama3.2:3b or qwen2.5-coder:1.5b).\n"
                    f"  -> Or increase --read-timeout.\n"
                    f"  -> Run `ollama ps` to confirm the model is loaded, not still "
                    f"loading into memory on first use."
                )
            print(f"   (read timeout, retrying in {backoff}s -- "
                  f"attempt {attempt}/{max_conn_retries})")
            time.sleep(backoff)
            backoff *= 2
        except requests.exceptions.HTTPError as e:
            raise OllamaError(f"Ollama returned HTTP error: {e}")

    raise OllamaError("Exhausted retries calling Ollama.")


# --------------------------------------------------------------------------- #
# 4. OUTPUT PARSING
# --------------------------------------------------------------------------- #

CODE_FENCE_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def extract_code(raw_text: str) -> str:
    """Pull the python code out of a fenced block; fall back to raw text."""
    match = CODE_FENCE_RE.search(raw_text)
    if match:
        return match.group(1).strip()
    return raw_text.strip()


def validate_syntax(code: str):
    """Return (is_valid, error_message)."""
    try:
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        return False, f"{e.__class__.__name__}: {e.msg} (line {e.lineno}, col {e.offset})"


def summarize(code: str) -> dict:
    """Lightweight, regex-based report -- no extra LLM call needed."""
    def count(pattern):
        return len(re.findall(pattern, code, re.MULTILINE))

    return {
        "total_test_functions": count(r"^\s*def test_"),
        "happy_path_blocks": count(r"#\s*-+\s*Happy path"),
        "boundary_blocks": count(r"#\s*-+\s*Boundary value"),
        "edge_case_blocks": count(r"#\s*-+\s*Edge cases"),
        "error_handling_blocks": count(r"#\s*-+\s*Error handling"),
        "parametrize_uses": count(r"@pytest\.mark\.parametrize"),
    }


# --------------------------------------------------------------------------- #
# 5. AST-BASED MERGE OF MULTIPLE BATCH MODULES INTO ONE FILE
# --------------------------------------------------------------------------- #

def merge_batches(batch_codes):
    """
    Merge multiple syntactically-valid python modules into one:
    - keeps the module docstring from the FIRST batch only
    - de-duplicates import statements (by their unparsed text), preserving order
    - keeps all other top-level statements (constants, fixtures, parametrize
      data tables), de-duplicating by assigned name(s)
    - keeps all function defs, renaming on name collision to avoid clobbering
    """
    docstring = None
    import_texts = []
    seen_imports = set()
    body_parts = []
    seen_assign_names = set()
    func_nodes = []
    seen_func_names = set()

    for bi, code in enumerate(batch_codes):
        tree = ast.parse(code)
        body = list(tree.body)

        # Strip a leading string-literal expression (the module docstring)
        if body and isinstance(body[0], ast.Expr) and isinstance(
                getattr(body[0], "value", None), ast.Constant) and isinstance(
                body[0].value.value, str):
            doc_node = body.pop(0)
            if bi == 0:
                docstring = doc_node.value.value

        for node in body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                text = ast.unparse(node)
                if text not in seen_imports:
                    seen_imports.add(text)
                    import_texts.append(text)

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                if name in seen_func_names:
                    new_name = f"{name}__b{bi + 1}"
                    suffix = 2
                    while new_name in seen_func_names:
                        new_name = f"{name}__b{bi + 1}_{suffix}"
                        suffix += 1
                    node.name = new_name
                    name = new_name
                seen_func_names.add(name)
                func_nodes.append(node)

            elif isinstance(node, ast.Assign) and all(
                    isinstance(t, ast.Name) for t in node.targets):
                target_names = tuple(t.id for t in node.targets)
                if target_names not in seen_assign_names:
                    seen_assign_names.add(target_names)
                    body_parts.append(ast.unparse(node))

            else:
                body_parts.append(ast.unparse(node))

    sections = []
    if docstring:
        sections.append('"""' + docstring.replace('"""', '\\"\\"\\"') + '"""')
    if import_texts:
        sections.append("\n".join(import_texts))
    if body_parts:
        sections.append("\n\n".join(body_parts))
    if func_nodes:
        sections.append("\n\n\n".join(ast.unparse(fn) for fn in func_nodes))

    return "\n\n\n".join(s for s in sections if s.strip()) + "\n"


# --------------------------------------------------------------------------- #
# 6. GENERATION PIPELINES (single-shot and batched)
# --------------------------------------------------------------------------- #

def generate_one_module(messages, ollama_kwargs, max_retries, label=""):
    """Call the model, extract code, validate syntax, self-heal on error."""
    prefix = f"{label}: " if label else ""
    print(f"-> {prefix}calling model...")
    raw = call_ollama(messages=messages, **ollama_kwargs)
    code = extract_code(raw)
    valid, error = validate_syntax(code)

    attempt = 0
    while not valid and attempt < max_retries:
        attempt += 1
        print(f"-> {prefix}syntax error, asking model to fix "
              f"(attempt {attempt}/{max_retries}): {error}")
        messages = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": build_fix_prompt(code, error)},
        ]
        raw = call_ollama(messages=messages, **ollama_kwargs)
        code = extract_code(raw)
        valid, error = validate_syntax(code)

    if not valid:
        print(f"WARNING: {prefix}could not obtain valid syntax after "
              f"{max_retries} retries. Keeping best-effort output. "
              f"Last error: {error}")

    return code, valid


def generate_single_shot(story_text, ollama_kwargs, max_retries):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(story_text)},
    ]
    return generate_one_module(messages, ollama_kwargs, max_retries)


def generate_batched(preamble, items, batch_size, ollama_kwargs, max_retries):
    batches = chunk_items(items, batch_size)
    total = len(batches)
    print(f"-> Story has {len(items)} numbered acceptance criteria -> "
          f"splitting into {total} batch(es) of up to {batch_size} each.")

    batch_codes = []
    assumptions = ""
    all_valid = True

    for idx, batch in enumerate(batches, start=1):
        batch_text = "\n\n".join(batch)
        if idx == 1:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(
                    (preamble + "\n\n" + batch_text) if preamble else batch_text)},
            ]
        else:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT + BATCH_SYSTEM_ADDENDUM},
                {"role": "user", "content": build_batch_prompt(
                    preamble, assumptions, batch_text, idx, total)},
            ]

        code, valid = generate_one_module(
            messages, ollama_kwargs, max_retries, label=f"batch {idx}/{total}")
        batch_codes.append(code)
        all_valid = all_valid and valid

        if idx == 1:
            assumptions = extract_assumptions(code)

    print("-> Merging batches into a single test module...")
    merged = merge_batches(batch_codes)
    valid, error = validate_syntax(merged)
    if not valid:
        print(f"WARNING: merged file failed validation ({error}); this "
              f"shouldn't normally happen since each batch was pre-validated. "
              f"Writing it anyway for manual inspection.")
        all_valid = False
    return merged, all_valid


def generate_stub(test_code, ollama_kwargs, max_retries):
    """Ask the model for a minimal solution.py scaffold matching the tests."""
    messages = [
        {"role": "system", "content": STUB_SYSTEM_PROMPT},
        {"role": "user", "content": build_stub_prompt(test_code)},
    ]
    return generate_one_module(messages, ollama_kwargs, max_retries, label="stub")


# --------------------------------------------------------------------------- #
# 7. MAIN
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(
        description="Generate a PyTest suite (happy-path + boundary + edge "
                    "cases) from a user story, using a local Ollama model.")
    parser.add_argument("-i", "--input", required=True,
                         help="Path to the user story / acceptance criteria file (.txt/.md)")
    parser.add_argument("-o", "--output", default="test_generated.py",
                         help="Output PyTest file path (default: test_generated.py)")
    parser.add_argument("-m", "--model", default="llama3.1",
                         help="Ollama model name (default: llama3.1). "
                              "A code-focused model like qwen2.5-coder:7b or "
                              "deepseek-coder-v2 will give better results.")
    parser.add_argument("--host", default="http://localhost:11434",
                         help="Ollama server URL (default: http://localhost:11434)")
    parser.add_argument("--temperature", type=float, default=0.2)

    # Timeouts / retries for the HTTP call itself
    parser.add_argument("--connect-timeout", type=int, default=10,
                         help="Seconds to wait for the initial connection (default: 10)")
    parser.add_argument("--read-timeout", type=int, default=60,
                         help="Seconds allowed of SILENCE between streamed tokens "
                              "before treating it as a stall (default: 60). Since "
                              "responses are streamed, this does NOT need to cover "
                              "the whole generation -- only gaps between tokens.")
    parser.add_argument("--max-conn-retries", type=int, default=3,
                         help="Retries (with exponential backoff) on connection/"
                              "timeout errors (default: 3)")

    # Model context/output size
    parser.add_argument("--num-ctx", type=int, default=8192,
                         help="Context window to request from Ollama (default: 8192). "
                              "Lower this if your machine runs out of memory.")
    parser.add_argument("--num-predict", type=int, default=-1,
                         help="Max tokens to generate; -1 = until natural stop "
                              "(default: -1)")

    # Syntax self-healing
    parser.add_argument("--max-retries", type=int, default=2,
                         help="Self-healing retries per batch if generated code "
                              "has a syntax error (default: 2)")

    # Batching for large stories
    parser.add_argument("--batch-size", type=int, default=8,
                         help="Acceptance criteria per batch when batch mode is "
                              "used (default: 8)")
    parser.add_argument("--batch-threshold", type=int, default=10,
                         help="If the story has more numbered acceptance criteria "
                              "than this, automatically switch to batch mode "
                              "(default: 10)")
    parser.add_argument("--no-batch", action="store_true",
                         help="Force single-shot generation even for large stories "
                              "(may hit timeouts/truncation on very large stories)")
    parser.add_argument("--force-batch", action="store_true",
                         help="Force batch mode even if the story is under the "
                              "batch threshold")

    parser.add_argument("--verify", action="store_true",
                         help="After writing the file, run `pytest --collect-only` "
                              "on it to confirm PyTest can at least parse/collect it")
    parser.add_argument("--with-stub", action="store_true",
                         help="Also generate a minimal solution_stub.py scaffold "
                              "(every function raises NotImplementedError) so the "
                              "tests are importable/collectible immediately. "
                              "Rename it to solution.py (or point your real module "
                              "at the same names) and fill in real logic.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Parse the story and print acceptance-criteria and batching "
                              "statistics without contacting Ollama. "
                              "Useful for offline demos and CI checks.")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"ERROR: Input file not found: {input_path}")

    story_text = input_path.read_text(encoding="utf-8")
    if not story_text.strip():
        sys.exit("ERROR: Input file is empty.")

    ollama_kwargs = dict(
        model=args.model,
        host=args.host,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        num_predict=args.num_predict,
        connect_timeout=args.connect_timeout,
        read_timeout=args.read_timeout,
        max_conn_retries=args.max_conn_retries,
    )

    preamble, items = parse_acceptance_items(story_text)
    use_batch = (not args.no_batch) and (
        args.force_batch or len(items) > args.batch_threshold
    )

    # ------------------------------------------------------------------ #
    # DRY-RUN MODE: show parsing/batching statistics, skip Ollama entirely
    # ------------------------------------------------------------------ #
    if args.dry_run:
        from math import ceil
        sep = "=" * 60
        print(sep)
        print("  AUTOMATED TEST CASE GENERATION  --  DRY-RUN MODE")
        print(sep)
        print(f"  Input file : {input_path}")
        print(f"  Preamble   : {len(preamble)} characters")
        print(f"  Acceptance criteria found: {len(items)}")
        if use_batch:
            n_batches = ceil(len(items) / args.batch_size)
            print(f"  Batch mode : ENABLED  "
                  f"(threshold={args.batch_threshold}, batch_size={args.batch_size})")
            print(f"  Batches    : {n_batches}")
            for i in range(n_batches):
                chunk = items[i * args.batch_size:(i + 1) * args.batch_size]
                print(f"    Batch {i + 1:>2}: {len(chunk)} criteria")
        else:
            print(f"  Batch mode : DISABLED "
                  f"(story is under threshold of {args.batch_threshold} criteria)")
        print()
        print("  In live mode the tool would:")
        print(f"    1. Send each batch to Ollama (model: {args.model})")
        print(f"    2. Auto-heal any syntax errors (max retries: {args.max_retries})")
        print("    3. AST-merge batch outputs into one clean PyTest module")
        print(f"    4. Write the suite to: {args.output}")
        print()
        print("  [dry-run] Ollama call skipped. "
              "Re-run without --dry-run to generate a real test suite.")
        print(sep)
        return

    try:
        if use_batch and items:
            code, valid = generate_batched(
                preamble, items, args.batch_size, ollama_kwargs, args.max_retries)
        else:
            code, valid = generate_single_shot(story_text, ollama_kwargs, args.max_retries)
    except OllamaError as e:
        sys.exit(f"ERROR: {e}")

    code = ensure_pytest_import(code)

    output_path = Path(args.output)
    output_path.write_text(code, encoding="utf-8")
    print(f"-> Wrote {output_path} ({'valid' if valid else 'INVALID -- needs manual fix'} syntax)")

    stats = summarize(code)
    print("-> Summary:")
    for k, v in stats.items():
        print(f"     {k}: {v}")

    if args.with_stub:
        try:
            stub_code, stub_valid = generate_stub(code, ollama_kwargs, args.max_retries)
        except OllamaError as e:
            print(f"WARNING: could not generate stub: {e}")
        else:
            stub_path = write_stub_module(stub_code, output_path)
            stub_path.write_text(stub_code, encoding="utf-8")
            print(f"-> Wrote {stub_path} ({'valid' if stub_valid else 'INVALID'} syntax)")
            print(f"   This is SCAFFOLDING ONLY -- every function raises "
                  f"NotImplementedError. Rename it to solution.py (or copy its "
                  f"function signatures into your real module) and fill in the "
                  f"actual logic; the tests will then fail with real assertion "
                  f"errors instead of import errors, guiding your implementation.")

    if args.verify:
        import subprocess
        print("-> Running `pytest --collect-only` to sanity-check the file...")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", str(output_path)],
            capture_output=True, text=True,
        )
        print(result.stdout[-3000:])
        if result.returncode != 0:
            print(result.stderr[-2000:])
            print("NOTE: Collection errors are expected if `solution.py` "
                  "(the module under test) doesn't exist yet -- that's normal "
                  "until you implement it or point the import at your real code.")


if __name__ == "__main__":
    main()