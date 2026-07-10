#!/usr/bin/env python3
"""
log_analyzer.py
================
AI-powered log analysis for root cause identification.

Ingests application crash logs / stack traces, and for each distinct error
found, asks an LLM to produce: a plain-English summary, the likely
offending file/line, a root-cause hypothesis, and a suggested fix or
workaround.

Two backends are supported:
  - ollama (default): free, local, runs entirely on your machine via
    https://ollama.com. No API key, no per-token cost, nothing leaves
    your machine. Requires `ollama serve` running and a model pulled.
  - anthropic: the Claude API. Higher quality, needs ANTHROPIC_API_KEY.

Usage
-----
    # Analyze a log file with local Ollama (default, free)
    python log_analyzer.py crash.log

    # Use a specific local model
    python log_analyzer.py crash.log --model qwen2.5-coder

    # Use the Claude API instead
    python log_analyzer.py crash.log --backend anthropic

    # Point at your source checkout so real code context can be pulled in
    python log_analyzer.py crash.log --source-dir ./myapp

    # Pipe logs in directly
    tail -n 500 /var/log/app.log | python log_analyzer.py -

    # Just parse + show what would be sent to the model, no calls/cost
    python log_analyzer.py crash.log --dry-run

    # Write a markdown report instead of printing to console
    python log_analyzer.py crash.log -o report.md --format markdown

See README.md for full setup instructions for either backend.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

# Force UTF-8 stdout/stderr on Windows to avoid cp1252 codec errors
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass # fallback for older python versions

from analysis_common import AnalysisResult
from ai_client import AnthropicBackend, DEFAULT_MODEL as ANTHROPIC_DEFAULT_MODEL
from ollama_client import OllamaBackend, DEFAULT_MODEL as OLLAMA_DEFAULT_MODEL
from context_builder import build_prompt_context, ContextBudgetReport, redact
from parsers import ParsedError, dedupe, iter_parse_file, parse_generic, iter_parse_lines

BACKEND_DEFAULT_MODELS = {"ollama": OLLAMA_DEFAULT_MODEL, "anthropic": ANTHROPIC_DEFAULT_MODEL}


def build_backend(args: argparse.Namespace):
    if args.backend == "ollama":
        return OllamaBackend(model=args.model, host=args.ollama_host)
    return AnthropicBackend(api_key=args.api_key, model=args.model)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AI-powered crash log analysis for root cause identification.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("input", help="Path to a log file, or '-' to read from stdin")
    p.add_argument("--source-dir", help="Path to your source checkout, used to pull in "
                                         "real code context around the offending line")
    p.add_argument("-o", "--output", help="Write report to this file instead of stdout")
    p.add_argument("--format", choices=["console", "markdown", "json"], default="console",
                    help="Output format (default: console)")
    p.add_argument("--backend", choices=["ollama", "anthropic"], default="ollama",
                    help="Which LLM backend to use (default: ollama -- free, local, no API key)")
    p.add_argument("--model", default=None,
                    help="Model to use. Defaults to 'llama3.1' for --backend ollama, "
                         f"'{ANTHROPIC_DEFAULT_MODEL}' for --backend anthropic")
    p.add_argument("--ollama-host", default=None,
                    help="Ollama server URL (default: http://localhost:11434, or $OLLAMA_HOST)")
    p.add_argument("--api-key", help="Anthropic API key, only used with --backend anthropic "
                                      "(defaults to ANTHROPIC_API_KEY env var)")
    p.add_argument("--max-context-tokens", type=int, default=4000,
                    help="Token budget per error sent to the model (default: 4000)")
    p.add_argument("--context-lines", type=int, default=6,
                    help="Lines of source code to show above/below the offending line (default: 6)")
    p.add_argument("--max-errors", type=int, default=10,
                    help="Max number of distinct errors to analyze, after dedup (default: 10)")
    p.add_argument("--dry-run", action="store_true",
                    help="Parse and build context only; skip model calls (no cost, no network)")
    p.add_argument("--no-redact", action="store_true",
                    help="Disable automatic redaction of secrets/PII before sending to the model")
    p.add_argument("--verbose", "-v", action="store_true", help="Print progress to stderr")
    args = p.parse_args(argv)
    if args.model is None:
        args.model = BACKEND_DEFAULT_MODELS[args.backend]
    return args


def log(msg: str, verbose: bool) -> None:
    if verbose:
        print(f"[log-analyzer] {msg}", file=sys.stderr)


def collect_errors(args: argparse.Namespace) -> List[ParsedError]:
    if args.input == "-":
        text = sys.stdin.read()
        errors = list(iter_parse_lines(text.splitlines(keepends=True)))
        if not errors:
            errors = parse_generic(text)
    else:
        errors = list(iter_parse_file(args.input))
        if not errors:
            with open(args.input, "r", encoding="utf-8", errors="replace") as f:
                errors = parse_generic(f.read())
    errors = dedupe(errors)
    if not args.no_redact:
        # Redact secrets in the parsed error itself (not just the AI-bound
        # context) so report titles / JSON output don't leak them either.
        for e in errors:
            e.message = redact(e.message)
            e.raw_block = redact(e.raw_block)
            e.context_before = redact(e.context_before)
    return errors


class Finding:
    """One analyzed error, bundling the parsed error, the context that was
    sent, the budget report, and the AI's analysis (if any)."""

    def __init__(self, error: ParsedError, context_text: str,
                 budget: ContextBudgetReport, analysis: Optional[AnalysisResult]):
        self.error = error
        self.context_text = context_text
        self.budget = budget
        self.analysis = analysis


def run(args: argparse.Namespace) -> List[Finding]:
    errors = collect_errors(args)
    log(f"found {len(errors)} distinct error(s) after dedup", args.verbose)

    if not errors:
        return []

    analyzed = errors[: args.max_errors]
    skipped = len(errors) - len(analyzed)
    if skipped > 0:
        log(f"analyzing top {len(analyzed)}; {skipped} more found but skipped "
            f"(raise --max-errors to include them)", args.verbose)

    client = None if args.dry_run else build_backend(args)
    if client is not None and args.backend == "ollama":
        preflight_error = client.check_available()
        if preflight_error:
            raise RuntimeError(preflight_error)

    findings: List[Finding] = []
    for i, error in enumerate(analyzed, 1):
        log(f"[{i}/{len(analyzed)}] building context for {error.error_type}: {error.message[:60]}",
            args.verbose)
        context_text, budget = build_prompt_context(
            error,
            source_dir=args.source_dir,
            max_tokens=args.max_context_tokens,
            context_lines=args.context_lines,
            do_redact=not args.no_redact,
        )
        analysis = None
        if not args.dry_run:
            log(f"[{i}/{len(analyzed)}] calling {args.backend}:{args.model} (~{budget.estimated_tokens} input tokens)",
                args.verbose)
            analysis = client.analyze(context_text)
            if analysis.error:
                log(f"[{i}/{len(analyzed)}] WARNING: {analysis.error}", args.verbose)
        findings.append(Finding(error, context_text, budget, analysis))

    return findings


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def render_console(findings: List[Finding], dry_run: bool) -> str:
    out = []
    out.append("=" * 78)
    out.append(f"  LOG ANALYSIS REPORT  --  {len(findings)} distinct issue(s)")
    out.append("=" * 78)
    for i, f in enumerate(findings, 1):
        e = f.error
        out.append("")
        out.append(f"[{i}] {e.error_type}: {e.message or '(no message)'}")
        out.append(f"    format: {e.format}   occurrences: {e.occurrence_count}"
                    + (f"   timestamp: {e.timestamp}" if e.timestamp else ""))
        top = e.likely_offending_frame()
        if top:
            loc = f"{top.file}:{top.line}" if top.line else top.file
            out.append(f"    top frame: {loc}" + (f" in {top.function}" if top.function else ""))
        if f.budget.notes:
            for n in f.budget.notes:
                out.append(f"    note: {n}")

        if dry_run:
            out.append("    [dry-run] context that would be sent to the AI:")
            out.append("    " + "-" * 60)
            for line in f.context_text.splitlines():
                out.append(f"    | {line}")
            out.append("    " + "-" * 60)
            continue

        a = f.analysis
        if a is None:
            out.append("    (not analyzed)")
            continue
        if a.error and not a.summary:
            out.append(f"    ANALYSIS FAILED: {a.error}")
            continue

        out.append(f"    Summary:     {a.summary}")
        out.append(f"    Likely file: {a.likely_file or 'unknown'}"
                    + (f":{a.likely_line}" if a.likely_line else ""))
        out.append(f"    Root cause:  {a.root_cause}")
        out.append(f"    Confidence:  {a.confidence}    Severity: {a.severity}")
        out.append(f"    Suggested fix:")
        for line in (a.suggested_fix or "").splitlines() or [""]:
            out.append(f"        {line}")
        if a.workaround:
            out.append(f"    Workaround:  {a.workaround}")
        if a.error:
            out.append(f"    note: {a.error}")
    out.append("")
    out.append("=" * 78)
    return "\n".join(out)


def render_markdown(findings: List[Finding], dry_run: bool) -> str:
    out = [f"# Log Analysis Report\n", f"Found **{len(findings)}** distinct issue(s).\n"]
    for i, f in enumerate(findings, 1):
        e = f.error
        out.append(f"## {i}. `{e.error_type}`: {e.message or '(no message)'}\n")
        meta = f"- **Format:** {e.format}  \n- **Occurrences:** {e.occurrence_count}  "
        if e.timestamp:
            meta += f"\n- **Timestamp:** {e.timestamp}  "
        out.append(meta + "\n")
        top = e.likely_offending_frame()
        if top:
            loc = f"{top.file}:{top.line}" if top.line else top.file
            out.append(f"- **Top frame:** `{loc}`" + (f" in `{top.function}`" if top.function else "") + "\n")
        if f.budget.notes:
            out.append("- **Notes:** " + "; ".join(f.budget.notes) + "\n")

        if dry_run:
            out.append("\n<details><summary>Context sent to AI (dry-run)</summary>\n")
            out.append(f"```\n{f.context_text}\n```\n")
            out.append("</details>\n")
            continue

        a = f.analysis
        if a is None:
            out.append("\n_Not analyzed._\n")
            continue
        if a.error and not a.summary:
            out.append(f"\n**Analysis failed:** {a.error}\n")
            continue

        out.append(f"\n**Summary:** {a.summary}\n")
        out.append(f"\n**Likely offending location:** `{a.likely_file or 'unknown'}"
                    + (f":{a.likely_line}`" if a.likely_line else "`") + "\n")
        out.append(f"\n**Root cause:** {a.root_cause}\n")
        out.append(f"\n**Confidence:** {a.confidence} &nbsp;&nbsp; **Severity:** {a.severity}\n")
        out.append(f"\n**Suggested fix:**\n\n```\n{a.suggested_fix}\n```\n")
        if a.workaround:
            out.append(f"\n**Workaround:** {a.workaround}\n")
        if a.error:
            out.append(f"\n> note: {a.error}\n")
        out.append("\n---\n")
    return "\n".join(out)


def render_json(findings: List[Finding], dry_run: bool) -> str:
    payload = []
    for f in findings:
        e = f.error
        top = e.likely_offending_frame()
        item = {
            "error_type": e.error_type,
            "message": e.message,
            "format": e.format,
            "occurrences": e.occurrence_count,
            "timestamp": e.timestamp,
            "top_frame": (f"{top.file}:{top.line}" if top and top.line else (top.file if top else None)),
            "context_notes": f.budget.notes,
            "estimated_context_tokens": f.budget.estimated_tokens,
        }
        if dry_run:
            item["context_sent"] = f.context_text
        elif f.analysis:
            a = f.analysis
            item["analysis"] = {
                "summary": a.summary,
                "likely_file": a.likely_file,
                "likely_line": a.likely_line,
                "root_cause": a.root_cause,
                "confidence": a.confidence,
                "suggested_fix": a.suggested_fix,
                "workaround": a.workaround,
                "severity": a.severity,
                "error": a.error,
                "input_tokens": a.input_tokens,
                "output_tokens": a.output_tokens,
            }
        payload.append(item)
    return json.dumps({"issues": payload}, indent=2)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    try:
        findings = run(args)
    except FileNotFoundError:
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if not findings:
        print("No errors or exceptions were detected in the input.", file=sys.stderr)
        return 0

    renderer = {"console": render_console, "markdown": render_markdown, "json": render_json}[args.format]
    report = renderer(findings, args.dry_run)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(report)

    total_in = sum((f.analysis.input_tokens if f.analysis else 0) for f in findings)
    total_out = sum((f.analysis.output_tokens if f.analysis else 0) for f in findings)
    if total_in or total_out:
        if args.backend == "ollama":
            log(f"total usage: {total_in} prompt tokens, {total_out} generated tokens "
                f"(local/free -- no cost)", args.verbose)
        else:
            log(f"total usage: {total_in} input tokens, {total_out} output tokens "
                f"(see current pricing at https://docs.claude.com/en/docs/about-claude/pricing)",
                args.verbose)

    return 0


if __name__ == "__main__":
    sys.exit(main())
