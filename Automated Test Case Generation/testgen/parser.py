"""
testgen/parser.py
=================
Acceptance-criteria extraction and batch-chunking utilities.

This module is responsible for splitting a user story / acceptance-criteria
document into structured pieces that can be fed to the LLM individually
(batch mode) or as a whole (single-shot mode).

Public API
----------
parse_acceptance_items(story_text) -> (preamble, [item, item, ...])
chunk_items(items, batch_size)     -> [[batch], [batch], ...]
extract_assumptions(code)          -> str  (module docstring from generated code)
"""

import ast
import re
from typing import List, Tuple

from testgen.constants import NUMBERED_ITEM_PATTERN


# Pre-compiled regex for performance
_NUMBERED_ITEM_RE = re.compile(NUMBERED_ITEM_PATTERN, re.MULTILINE)


def parse_acceptance_items(story_text: str) -> Tuple[str, List[str]]:
    """
    Split a user story into a preamble and a list of numbered acceptance items.

    Splits on numbered list patterns (``1. ...``, ``2. ...``) found at the
    start of lines.  Each item includes any continuation / wrapped lines up to
    the next numbered item.

    If fewer than two numbered items are found the story is considered
    non-structured and ``(story_text, [])`` is returned, so the caller falls
    back to single-shot generation.

    Args:
        story_text: Full raw text of the user story or acceptance-criteria
                    document.

    Returns:
        A tuple of:
        - ``preamble`` (str): Text before the first numbered item.  Contains
          the story title / background / persona text.
        - ``items`` (list[str]): Each numbered acceptance criterion as its own
          string, including the number prefix and any continuation lines.
          Empty list if fewer than 2 numbered items were found.

    Example:
        >>> preamble, items = parse_acceptance_items(story_text)
        >>> len(items)  # number of acceptance criteria found
        12
    """
    matches = list(_NUMBERED_ITEM_RE.finditer(story_text))
    if len(matches) < 2:
        return story_text, []

    preamble = story_text[: matches[0].start()].strip()
    items: List[str] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(story_text)
        items.append(story_text[start:end].rstrip())

    return preamble, items


def chunk_items(items: List[str], batch_size: int) -> List[List[str]]:
    """
    Divide a flat list of acceptance-criteria strings into batches.

    Args:
        items:      Flat list of acceptance-criterion strings (one per item).
        batch_size: Maximum number of items per batch.

    Returns:
        A list of batches, where each batch is a sub-list of at most
        ``batch_size`` items.

    Example:
        >>> chunks = chunk_items(items, batch_size=8)
        >>> len(chunks)   # number of batches
        4
    """
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def extract_assumptions(code: str) -> str:
    """
    Extract the module-level docstring from a generated PyTest module.

    The ASSUMPTIONS section (describing the inferred function/class signatures)
    is embedded in the module docstring by convention.  This function pulls
    that string out so that later batches can be told to reuse the same API.

    Args:
        code: A string containing syntactically valid (or best-effort) Python
              source code for a PyTest module.

    Returns:
        The module-level docstring as a plain string, or an empty string if
        the code has no docstring or cannot be parsed.
    """
    try:
        tree = ast.parse(code)
        return ast.get_docstring(tree) or ""
    except SyntaxError:
        return ""
