"""
vrt/cli.py
==========
CLI argument parsing and orchestration entry point for the VRT package.

This module re-exports ``parse_args`` and ``main`` from the canonical flat
entry-point ``visual_regressor.py`` so they can also be imported from the
``vrt`` package path.

The CLI exposes two required arguments (``--baseline`` and ``--current``)
plus a rich set of optional flags for AI settings, comparison thresholds,
output formats, and operational modes.  See ``visual_regressor.py`` for the
full argument definitions.
"""

try:
    from visual_regressor import parse_args, run, main
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from visual_regressor import parse_args, run, main

__all__ = ["parse_args", "run", "main"]
