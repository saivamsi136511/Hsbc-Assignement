"""
vrt/utils.py
============
Utility helpers for the Visual Regression Testing package.

Provides:
- Logging helper: ``log(msg, verbose)`` — writes progress to stderr when verbose mode is on.
- Ignore-region parser: ``parse_ignore_regions(raw)`` — converts ``X,Y,W,H`` strings
  to ``(x, y, w, h)`` tuples for dynamic content masking.

These utilities are shared across the CLI, processor, and AI modules
to avoid duplication.
"""

import sys
from typing import List, Optional, Tuple


def log(msg: str, verbose: bool) -> None:
    """
    Write a progress message to stderr when verbose mode is enabled.

    Args:
        msg:     The progress message to display.
        verbose: If ``True``, print the message; otherwise do nothing.

    Returns:
        None. Side effect: writes to ``sys.stderr`` when verbose is True.
    """
    if verbose:
        print(f"[vrt] {msg}", file=sys.stderr)


def parse_ignore_regions(
    raw: Optional[List[str]],
) -> List[Tuple[int, int, int, int]]:
    """
    Parse a list of ``"X,Y,W,H"`` strings into pixel-rectangle tuples.

    Used to convert ``--ignore-region`` CLI arguments into the format expected
    by the ``ImageProcessor``.  Regions cover dynamic content zones (timestamps,
    ads, live feeds) that would cause false positives on every run.

    Invalid entries are silently skipped with a warning to stderr.

    Args:
        raw: List of strings in the format ``"X,Y,W,H"`` where all values
             are non-negative integers.  ``None`` or empty list produces
             no regions.

    Returns:
        List of ``(x, y, width, height)`` tuples.  Empty list if no valid
        regions were parsed.

    Example:
        >>> parse_ignore_regions(["0,0,200,60", "800,0,100,30"])
        [(0, 0, 200, 60), (800, 0, 100, 30)]
    """
    regions: List[Tuple[int, int, int, int]] = []
    for s in (raw or []):
        try:
            x, y, w, h = (int(v.strip()) for v in s.split(","))
            regions.append((x, y, w, h))
        except ValueError:
            print(
                f"[vrt] WARNING: could not parse ignore region '{s}' (expected X,Y,W,H)",
                file=sys.stderr,
            )
    return regions
