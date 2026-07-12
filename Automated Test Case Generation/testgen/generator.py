"""
testgen/generator.py
====================
High-level LLM generation pipelines for the test case generation workflow.

Provides three public functions:
- ``generate_single_shot`` — one model call for small user stories.
- ``generate_batched`` — split + generate + merge for large stories.
- ``generate_stub`` — generate a minimal solution.py scaffold from tests.

Each pipeline calls the Ollama client internally and delegates:
- Code extraction and syntax validation to ``testgen.output``
- Prompt building to ``testgen.prompts``
- Batch splitting and assumption extraction to ``testgen.parser``
- Batch merging to ``testgen.merge``
"""

from typing import Dict, List, Tuple

from testgen.ollama_client import call_ollama
from testgen.prompts import (
    SYSTEM_PROMPT,
    BATCH_SYSTEM_ADDENDUM,
    STUB_SYSTEM_PROMPT,
    build_user_prompt,
    build_batch_prompt,
    build_fix_prompt,
    build_stub_prompt,
)
from testgen.parser import chunk_items, extract_assumptions
from testgen.merge import merge_batches
from testgen.output import extract_code, validate_syntax


def generate_one_module(
    messages: List[Dict[str, str]],
    ollama_kwargs: Dict,
    max_retries: int,
    label: str = "",
) -> Tuple[str, bool]:
    """
    Call the LLM, extract generated code, validate syntax, and self-heal on error.

    On a syntax error the exact error message is sent back to the model with a
    request to return a corrected version.  This self-healing loop runs up to
    ``max_retries`` times before giving up and returning the best-effort output.

    Args:
        messages:      Conversation history in ``[{"role": ..., "content": ...}]`` format.
        ollama_kwargs: Keyword arguments forwarded to ``call_ollama`` (model, host, etc.).
        max_retries:   Number of self-healing attempts allowed on syntax errors.
        label:         Human-readable label for progress output (e.g. ``"batch 1/4"``).

    Returns:
        A tuple ``(code, is_valid)`` where ``code`` is the extracted Python source
        string and ``is_valid`` indicates whether it passed ``ast.parse``.
    """
    prefix = f"{label}: " if label else ""
    print(f"-> {prefix}calling model...")
    raw = call_ollama(messages=messages, **ollama_kwargs)
    code = extract_code(raw)
    valid, error = validate_syntax(code)

    attempt = 0
    while not valid and attempt < max_retries:
        attempt += 1
        print(
            f"-> {prefix}syntax error, asking model to fix "
            f"(attempt {attempt}/{max_retries}): {error}"
        )
        messages = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": build_fix_prompt(code, error)},
        ]
        raw = call_ollama(messages=messages, **ollama_kwargs)
        code = extract_code(raw)
        valid, error = validate_syntax(code)

    if not valid:
        print(
            f"WARNING: {prefix}could not obtain valid syntax after "
            f"{max_retries} retries. Keeping best-effort output. "
            f"Last error: {error}"
        )

    return code, valid


def generate_single_shot(
    story_text: str,
    ollama_kwargs: Dict,
    max_retries: int,
) -> Tuple[str, bool]:
    """
    Generate a complete test suite in a single model call (small stories).

    Best for user stories with fewer than ``DEFAULT_BATCH_THRESHOLD`` numbered
    acceptance criteria.  For larger stories use ``generate_batched`` to avoid
    token-limit and timeout issues.

    Args:
        story_text:    Full text of the user story or acceptance-criteria document.
        ollama_kwargs: Keyword arguments for ``call_ollama``.
        max_retries:   Self-healing retry budget per generation attempt.

    Returns:
        ``(code, is_valid)`` — see ``generate_one_module``.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(story_text)},
    ]
    return generate_one_module(messages, ollama_kwargs, max_retries)


def generate_batched(
    preamble: str,
    items: List[str],
    batch_size: int,
    ollama_kwargs: Dict,
    max_retries: int,
) -> Tuple[str, bool]:
    """
    Generate a test suite from a large story by splitting it into batches.

    Each batch covers a subset of numbered acceptance criteria.  Batch 1
    establishes the assumed function/class signatures (captured from its
    ASSUMPTIONS docstring).  Subsequent batches are explicitly told to reuse
    that signature so the merged suite stays API-consistent.

    After all batches are generated the results are merged into one file
    using the AST-based merger (``testgen.merge.merge_batches``), which
    de-duplicates imports/constants and renames colliding function names.

    Args:
        preamble:    Story text before the first numbered item (background context).
        items:       List of numbered acceptance-criterion strings.
        batch_size:  Maximum items per batch.
        ollama_kwargs: Keyword arguments for ``call_ollama``.
        max_retries: Self-healing retry budget per batch.

    Returns:
        ``(merged_code, all_valid)`` where ``all_valid`` is ``True`` only if
        every individual batch and the final merge all passed syntax validation.
    """
    batches = chunk_items(items, batch_size)
    total = len(batches)
    print(
        f"-> Story has {len(items)} numbered acceptance criteria -> "
        f"splitting into {total} batch(es) of up to {batch_size} each."
    )

    batch_codes: List[str] = []
    assumptions = ""
    all_valid = True

    for idx, batch in enumerate(batches, start=1):
        batch_text = "\n\n".join(batch)
        if idx == 1:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(
                    (preamble + "\n\n" + batch_text) if preamble else batch_text
                )},
            ]
        else:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT + BATCH_SYSTEM_ADDENDUM},
                {"role": "user", "content": build_batch_prompt(
                    preamble, assumptions, batch_text, idx, total
                )},
            ]

        code, valid = generate_one_module(
            messages, ollama_kwargs, max_retries, label=f"batch {idx}/{total}"
        )
        batch_codes.append(code)
        all_valid = all_valid and valid

        if idx == 1:
            assumptions = extract_assumptions(code)

    print("-> Merging batches into a single test module...")
    merged = merge_batches(batch_codes)
    valid, error = validate_syntax(merged)
    if not valid:
        print(
            f"WARNING: merged file failed validation ({error}); this "
            f"shouldn't normally happen since each batch was pre-validated. "
            f"Writing it anyway for manual inspection."
        )
        all_valid = False

    return merged, all_valid


def generate_stub(
    test_code: str,
    ollama_kwargs: Dict,
    max_retries: int,
) -> Tuple[str, bool]:
    """
    Ask the model for a minimal solution.py scaffold that matches a test suite.

    Every function/class imported by the test file is defined in the stub with
    a body of ``raise NotImplementedError(...)``.  This makes the tests
    importable and collectable by pytest immediately, so developers see failing
    assertion errors rather than import errors as they fill in real logic.

    Args:
        test_code:     Full content of the generated PyTest module.
        ollama_kwargs: Keyword arguments for ``call_ollama``.
        max_retries:   Self-healing retry budget.

    Returns:
        ``(stub_code, is_valid)`` — see ``generate_one_module``.
    """
    messages = [
        {"role": "system", "content": STUB_SYSTEM_PROMPT},
        {"role": "user", "content": build_stub_prompt(test_code)},
    ]
    return generate_one_module(messages, ollama_kwargs, max_retries, label="stub")
