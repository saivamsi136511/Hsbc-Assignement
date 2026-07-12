"""
testgen/output.py
=================
Code extraction, syntax validation, and suite summarisation utilities.

This module handles the post-processing of raw LLM responses:
- Extracting Python code from fenced markdown blocks.
- Validating syntax with ``ast.parse``.
- Ensuring required imports (``pytest``, ``from solution import ...``) are
  present in the generated file.
- Producing a lightweight human-readable summary of the generated suite.
- Writing a stub module to disk.

Public API
----------
extract_code(raw_text)       -> str   (Python code from ```python ... ``` block)
validate_syntax(code)        -> (bool, str | None)
ensure_pytest_import(code)   -> str   (code with missing imports injected)
summarize(code)              -> dict
write_stub_module(stub, out) -> Path
"""

import ast
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

from testgen.constants import (
    CODE_FENCE_PATTERN,
    PYTHON_BUILTINS,
    STUB_FILENAME,
    STUB_FALLBACK_FILENAME,
)


# Pre-compiled regex for code fence extraction
_CODE_FENCE_RE = re.compile(CODE_FENCE_PATTERN, re.DOTALL)


def extract_code(raw_text: str) -> str:
    """
    Extract Python source code from a fenced markdown block in the model response.

    Searches for a ````` ```python ... ``` ````` or ````` ``` ... ``` `````
    block and returns its content.  If no fenced block is found, the raw
    text is returned stripped (best-effort fallback for non-compliant output).

    Args:
        raw_text: Raw string response from the LLM, which may contain prose
                  before/after the code fence.

    Returns:
        The extracted Python source code as a plain string (no fence markers).
        Falls back to ``raw_text.strip()`` if no fence is found.
    """
    match = _CODE_FENCE_RE.search(raw_text)
    if match:
        return match.group(1).strip()
    return raw_text.strip()


def validate_syntax(code: str) -> Tuple[bool, Optional[str]]:
    """
    Check whether a Python source string is syntactically valid.

    Uses ``ast.parse`` so that no code is executed during validation.

    Args:
        code: Python source code to validate.

    Returns:
        A tuple ``(is_valid, error_message)``:
        - ``is_valid`` is ``True`` if the code parses without errors.
        - ``error_message`` is ``None`` on success, or a descriptive string
          (including line/column info) on failure.
    """
    try:
        ast.parse(code)
        return True, None
    except SyntaxError as exc:
        return False, f"{exc.__class__.__name__}: {exc.msg} (line {exc.lineno}, col {exc.offset})"


def ensure_pytest_import(code: str) -> str:
    """
    Ensure that ``import pytest`` and ``from solution import ...`` are present
    in the generated test module whenever they are needed.

    Parses the code with ``ast``, inspects all function calls, and injects
    any missing import statements immediately after the module docstring (if
    present) or at the top of the file.

    This is a best-effort post-processing step.  If the code is not parseable,
    it is returned unchanged.

    Args:
        code: Python source code for the generated test module.

    Returns:
        The source code string with any missing imports prepended or injected
        after the module docstring.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    imports_needed = []

    # Check for pytest usage
    if "@pytest.mark" in code or "pytest." in code:
        if not re.search(r"^\s*(import pytest|from pytest\s+import\b)", code, re.MULTILINE):
            imports_needed.append("import pytest")

    # Detect function calls that are not Python built-ins and not already imported
    solution_functions = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name not in PYTHON_BUILTINS:
                solution_functions.add(func_name)

    if solution_functions:
        existing_imports = re.findall(r"from solution import ([^\n]+)", code)
        existing_names: set = set()
        for imp in existing_imports:
            existing_names.update(name.strip() for name in imp.split(","))

        missing = solution_functions - existing_names
        if missing:
            imports_needed.append(f"from solution import {', '.join(sorted(missing))}")

    if not imports_needed:
        return code

    lines = code.splitlines()
    # Insert after module docstring if present
    if (tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(getattr(tree.body[0], "value", None), ast.Constant)
            and isinstance(tree.body[0].value.value, str)):
        insert_at = tree.body[0].end_lineno
        lines = lines[:insert_at] + imports_needed + lines[insert_at:]
    else:
        lines = imports_needed + lines

    return "\n".join(lines) + ("\n" if code.endswith("\n") else "")


def summarize(code: str) -> Dict[str, int]:
    """
    Produce a lightweight, regex-based summary of a generated test suite.

    Does not execute the code; uses regex pattern matching only.  Intended
    to give the user quick feedback on the coverage structure of the output.

    Args:
        code: Python source code for the generated test module.

    Returns:
        A dictionary with integer counts for:
        - ``total_test_functions``   — number of ``def test_`` functions
        - ``happy_path_blocks``      — ``# --- Happy path ---`` comment sections
        - ``boundary_blocks``        — ``# --- Boundary value ---`` sections
        - ``edge_case_blocks``       — ``# --- Edge cases ---`` sections
        - ``error_handling_blocks``  — ``# --- Error handling ---`` sections
        - ``parametrize_uses``       — ``@pytest.mark.parametrize`` decorators
    """
    def _count(pattern: str) -> int:
        return len(re.findall(pattern, code, re.MULTILINE))

    return {
        "total_test_functions":  _count(r"^\s*def test_"),
        "happy_path_blocks":     _count(r"#\s*-+\s*Happy path"),
        "boundary_blocks":       _count(r"#\s*-+\s*Boundary value"),
        "edge_case_blocks":      _count(r"#\s*-+\s*Edge cases"),
        "error_handling_blocks": _count(r"#\s*-+\s*Error handling"),
        "parametrize_uses":      _count(r"@pytest\.mark\.parametrize"),
    }


def write_stub_module(stub_code: str, output_path: Path) -> Path:
    """
    Write a generated solution stub to disk adjacent to the test file.

    Prefers ``solution.py`` as the filename.  If that file already exists,
    falls back to ``solution_stub.py`` to avoid overwriting a real implementation.

    Args:
        stub_code:   Python source code for the minimal stub module.
        output_path: Path to the generated test file.  The stub is written
                     in the same directory.

    Returns:
        The ``Path`` of the file that was written (either ``solution.py`` or
        ``solution_stub.py``).
    """
    preferred = output_path.with_name(STUB_FILENAME)
    if preferred.exists():
        fallback = output_path.with_name(STUB_FALLBACK_FILENAME)
        fallback.write_text(stub_code, encoding="utf-8")
        return fallback

    preferred.write_text(stub_code, encoding="utf-8")
    return preferred
