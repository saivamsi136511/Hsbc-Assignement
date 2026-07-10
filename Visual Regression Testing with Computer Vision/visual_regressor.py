#!/usr/bin/env python3
"""
visual_regressor.py
===================
CLI entry point for AI-powered visual regression testing.

Compares a **baseline** screenshot (how the UI should look) against a
**current** screenshot (from a new deployment) using a multi-layer
computer-vision approach and an optional local AI model via Ollama.

The tool avoids brittle pixel-by-pixel diffing by combining:
  • SSIM structural similarity
  • ORB feature matching for layout-shift detection
  • Canny edge-map comparison for missing/moved elements
  • Contour-based region detection (intelligent bounding boxes)
  • Colour histogram comparison for palette / stylesheet regressions

AI analysis uses a locally-running Ollama vision model (e.g. llava),
so there are NO paid API calls and NO data sent to third-party servers.

Quick start
-----------
    # Install dependencies
    pip install -r requirements.txt

    # Install & start Ollama, pull a vision model (one-time)
    ollama serve
    ollama pull llava

    # Run against sample screenshots (dry-run, no Ollama needed)
    python visual_regressor.py \\
        --baseline sample_screenshots/baseline.png \\
        --current  sample_screenshots/new_deployment.png \\
        --dry-run

    # Full run with Ollama AI analysis + HTML report
    python visual_regressor.py \\
        --baseline sample_screenshots/baseline.png \\
        --current  sample_screenshots/new_deployment.png \\
        --format html --output report.html

    # CI-friendly JSON output, fail on SSIM < 0.90
    python visual_regressor.py \\
        --baseline baseline.png --current current.png \\
        --threshold 0.90 --format json --output result.json

Exit codes
----------
    0  — Test passed (SSIM ≥ threshold)
    1  — Test failed or an error occurred
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from typing import List, Optional, Tuple

# Force UTF-8 stdout/stderr on Windows to avoid cp1252 codec errors
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass # fallback for older python versions

from image_processor import ImageProcessor
from ai_analyzer import OllamaAnalyzer, AIAnalysisResult, DEFAULT_MODEL
from reporter import Reporter


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AI-powered visual regression testing with OpenCV + Ollama.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required inputs
    p.add_argument("--baseline", required=True,
                   help="Path to the baseline (reference) screenshot.")
    p.add_argument("--current", required=True,
                   help="Path to the current (new deployment) screenshot.")

    # AI settings
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"Ollama vision model to use (default: {DEFAULT_MODEL}). "
                        "Requires the model to be pulled: ollama pull <model>")
    p.add_argument("--ollama-url", default="http://localhost:11434",
                   help="Ollama API base URL (default: http://localhost:11434)")

    # Comparison settings
    p.add_argument("--threshold", type=float, default=0.95,
                   help="SSIM score threshold for pass/fail (default: 0.95). "
                        "Range 0.0–1.0; lower = more permissive.")
    p.add_argument("--min-change-area", type=int, default=100,
                   help="Minimum changed-region area in pixels to report (default: 100). "
                        "Filters anti-aliasing / sub-pixel noise.")
    p.add_argument("--ignore-region", action="append", metavar="X,Y,W,H",
                   help="Pixel rectangle to ignore (dynamic content zone). "
                        "Repeatable. Example: --ignore-region 0,0,200,60")

    # Output settings
    p.add_argument("-o", "--output",
                   help="Write report to this file instead of stdout.")
    p.add_argument("--format", choices=["console", "html", "json"], default="console",
                   help="Output format (default: console).")
    p.add_argument("--output-dir", default="vrt_output",
                   help="Directory for saving diff images (default: vrt_output).")

    # Mode flags
    p.add_argument("--dry-run", action="store_true",
                   help="Run OpenCV analysis only; skip Ollama AI calls.")
    p.add_argument("--no-save-images", action="store_true",
                   help="Do not save diff/heatmap/annotated images to disk.")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Print progress messages to stderr.")

    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str, verbose: bool) -> None:
    if verbose:
        print(f"[vrt] {msg}", file=sys.stderr)


def parse_ignore_regions(raw: Optional[List[str]]) -> List[Tuple[int, int, int, int]]:
    """Parse --ignore-region X,Y,W,H strings into tuples."""
    regions = []
    for s in (raw or []):
        try:
            x, y, w, h = (int(v.strip()) for v in s.split(","))
            regions.append((x, y, w, h))
        except ValueError:
            print(f"[vrt] WARNING: could not parse ignore region '{s}' (expected X,Y,W,H)", file=sys.stderr)
    return regions


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    """Run the full visual regression pipeline. Returns exit code (0=pass, 1=fail)."""

    # ── 1. Validate inputs ──────────────────────────────────────────────────
    for path_attr, label in [("baseline", "baseline"), ("current", "current")]:
        path = getattr(args, path_attr)
        if not os.path.isfile(path):
            print(f"error: {label} image not found: {path!r}", file=sys.stderr)
            return 1

    ignore_regions = parse_ignore_regions(args.ignore_region)
    if ignore_regions:
        log(f"ignoring {len(ignore_regions)} dynamic region(s)", args.verbose)

    # ── 2. OpenCV image analysis ─────────────────────────────────────────────
    log("running multi-layer OpenCV comparison …", args.verbose)
    processor = ImageProcessor(
        ssim_threshold=args.threshold,
        min_change_area=args.min_change_area,
        ignore_regions=ignore_regions,
    )
    cv_result = processor.compare(args.baseline, args.current)

    if cv_result.error:
        print(f"error: image comparison failed: {cv_result.error}", file=sys.stderr)
        return 1

    log(
        f"SSIM={cv_result.ssim_score:.4f}  changed={cv_result.changed_percentage:.2f}%  "
        f"regions={len(cv_result.changed_regions)}  layout_shift={cv_result.layout_shift_detected}",
        args.verbose,
    )

    # ── 3. Save diff images ──────────────────────────────────────────────────
    image_paths: dict = {}
    if not args.no_save_images:
        log(f"saving diff images to '{args.output_dir}' …", args.verbose)
        image_paths = processor.save_diff_images(cv_result, args.output_dir)
        for name, path in image_paths.items():
            log(f"  saved {name}: {path}", args.verbose)

    # ── 4. Ollama AI analysis ────────────────────────────────────────────────
    ai_result: Optional[AIAnalysisResult] = None
    if not args.dry_run:
        log(f"sending to Ollama model '{args.model}' …", args.verbose)
        analyzer = OllamaAnalyzer(model=args.model, base_url=args.ollama_url)
        ai_result = analyzer.analyze(args.baseline, args.current, cv_result)
        if ai_result.error:
            log(f"WARNING: {ai_result.error}", args.verbose)
            log("Falling back to OpenCV-only report.", args.verbose)
        else:
            log(
                f"AI analysis done in {ai_result.elapsed_seconds}s  "
                f"(prompt={ai_result.prompt_tokens} tokens, "
                f"completion={ai_result.completion_tokens} tokens)",
                args.verbose,
            )
    else:
        log("dry-run: skipping Ollama AI analysis", args.verbose)

    # ── 5. Generate report ───────────────────────────────────────────────────
    reporter = Reporter(output_dir=args.output_dir)
    report = reporter.render(
        baseline_path=args.baseline,
        current_path=args.current,
        cv_result=cv_result,
        ai_result=ai_result,
        fmt=args.format,
        image_paths=image_paths,
    )

    if args.output:
        Reporter.write(report, args.output)
        print(f"Report written to: {args.output}", file=sys.stderr)
    else:
        print(report)

    # ── 6. Exit code ─────────────────────────────────────────────────────────
    if cv_result.passed:
        log(f"[PASSED] (SSIM {cv_result.ssim_score:.4f} >= threshold {args.threshold})", args.verbose)
        return 0
    else:
        log(f"[FAILED] (SSIM {cv_result.ssim_score:.4f} < threshold {args.threshold})", args.verbose)
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
