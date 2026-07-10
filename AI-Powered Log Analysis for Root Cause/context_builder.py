"""
context_builder.py
===================
Turns a ParsedError into a bounded, prioritized prompt payload for the AI.

Why this exists as its own module: crash logs are frequently far larger than
what's useful (or affordable) to send to a model -- a StackOverflowError can
have 5,000 frames, a log file can be gigabytes, and pulling in full source
files would blow past any reasonable context budget. This module decides,
under a token budget, what actually gets included and in what priority:

  1. error type + message                (always, tiny)
  2. the stack trace itself, bounded      (always, capped)
  3. source code around the likely        (best-effort, capped per frame)
     offending frame(s)
  4. preceding log lines for situational  (fills remaining budget)
     context

It also does basic secret redaction before anything leaves the machine.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from parsers import ParsedError, StackFrame

# Rough heuristic: ~4 chars/token for English text and code. Good enough for
# budgeting purposes; for exact counts in production, use the Anthropic API's
# messages.count_tokens() endpoint instead.
CHARS_PER_TOKEN = 4

MAX_FRAMES_HEAD = 12
MAX_FRAMES_TAIL = 5
DEFAULT_SOURCE_CONTEXT_LINES = 6
MAX_FRAMES_WITH_SOURCE = 3

_REDACT_PATTERNS = [
    (re.compile(r"sk[-_][a-zA-Z0-9_-]{10,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "[REDACTED_CARD_NUMBER]"),
    (re.compile(r'(?i)(password|passwd|secret|token)(["\']?\s*[:=]\s*)["\']?[^\s,"\']+'),
     r"\1\2[REDACTED]"),
]


def redact(text: str) -> str:
    for pattern, repl in _REDACT_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


@dataclass
class ContextBudgetReport:
    """Tracks what was included vs. dropped, so the user can see when
    truncation happened rather than silently getting a partial picture."""
    frames_included: int = 0
    frames_omitted: int = 0
    source_snippets_included: int = 0
    context_before_included: bool = False
    context_before_truncated: bool = False
    estimated_tokens: int = 0
    notes: List[str] = field(default_factory=list)


def _format_frames(frames: List[StackFrame]) -> tuple[str, int, int]:
    """Returns (formatted_text, included_count, omitted_count). Caps very
    long traces (e.g. deep recursion / stack overflow) to head + tail with
    an explicit omission marker, rather than either truncating silently or
    blowing the budget on thousands of near-identical frames."""
    if len(frames) <= MAX_FRAMES_HEAD + MAX_FRAMES_TAIL:
        shown = frames
        omitted = 0
    else:
        shown_head = frames[:MAX_FRAMES_HEAD]
        shown_tail = frames[-MAX_FRAMES_TAIL:]
        omitted = len(frames) - len(shown_head) - len(shown_tail)
        shown = shown_head + [None] + shown_tail  # type: ignore

    lines = []
    for f in shown:
        if f is None:
            lines.append(f"    ... [{omitted} intermediate frames omitted -- "
                          f"likely deep/recursive call chain] ...")
            continue
        loc = f"{f.file}:{f.line}" if f.line else f.file
        func = f" in {f.function}" if f.function else ""
        lines.append(f"    at {loc}{func}")
    included = len(shown) - (1 if omitted else 0)
    return "\n".join(lines), included, omitted


def _read_source_snippet(file_path: str, line_no: Optional[int],
                          source_dir: Optional[str],
                          context_lines: int) -> Optional[str]:
    """Best-effort lookup of real source code around the offending line.
    Tries the path as given, then relative to source_dir. Silently returns
    None if the file isn't available locally (very common -- the log may
    have been produced on a different machine/container than this one)."""
    if not line_no:
        return None
    candidates = [file_path]
    if source_dir:
        candidates.append(os.path.join(source_dir, file_path.lstrip("/")))
        candidates.append(os.path.join(source_dir, os.path.basename(file_path)))

    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                all_lines = fh.readlines()
        except OSError:
            continue
        start = max(0, line_no - 1 - context_lines)
        end = min(len(all_lines), line_no + context_lines)
        snippet_lines = []
        for i in range(start, end):
            marker = ">>" if (i + 1) == line_no else "  "
            snippet_lines.append(f"{marker} {i + 1:5d} | {all_lines[i].rstrip()}")
        return "\n".join(snippet_lines)
    return None


def build_prompt_context(
    error: ParsedError,
    source_dir: Optional[str] = None,
    max_tokens: int = 4000,
    context_lines: int = DEFAULT_SOURCE_CONTEXT_LINES,
    do_redact: bool = True,
) -> tuple[str, ContextBudgetReport]:
    """Assembles the final text block to send to the AI for one error,
    respecting max_tokens by dropping lower-priority sections first."""
    report = ContextBudgetReport()
    budget = max_tokens

    header = f"Error type: {error.error_type}\n"
    if error.message:
        header += f"Message: {error.message}\n"
    if error.timestamp:
        header += f"Timestamp: {error.timestamp}\n"
    if error.occurrence_count > 1:
        header += f"Occurrences in log: {error.occurrence_count}\n"
    header += f"Detected format: {error.format}\n"
    budget -= estimate_tokens(header)

    frames_text, included, omitted = _format_frames(error.frames)
    report.frames_included, report.frames_omitted = included, omitted
    if omitted:
        report.notes.append(f"{omitted} stack frames omitted to stay within context budget")
    frames_section = f"\nStack trace:\n{frames_text}\n" if frames_text else ""
    budget -= estimate_tokens(frames_section)

    # Source snippets for the frames most likely to be the actual bug,
    # capped so we don't pull in huge files or dozens of snippets.
    source_sections = []
    candidate_frames = sorted(
        error.frames,
        key=lambda f: 0 if f.is_likely_own_code(source_dir) else 1,
    )[:MAX_FRAMES_WITH_SOURCE]
    per_snippet_budget = max(0, budget) // 2  # never spend more than half remaining budget here
    for f in candidate_frames:
        if per_snippet_budget < 50:
            report.notes.append("skipped remaining source lookups: token budget exhausted")
            break
        snippet = _read_source_snippet(f.file, f.line, source_dir, context_lines)
        if snippet:
            cost = estimate_tokens(snippet)
            if cost > per_snippet_budget:
                # shrink context window for this frame rather than skip it entirely
                shrink_ratio = per_snippet_budget / max(cost, 1)
                new_lines = max(1, int(context_lines * shrink_ratio))
                snippet = _read_source_snippet(f.file, f.line, source_dir, new_lines)
            if snippet:
                source_sections.append(f"\nSource near {f.file}:{f.line}:\n{snippet}\n")
                report.source_snippets_included += 1
                per_snippet_budget -= estimate_tokens(snippet)
    if not source_sections and error.frames:
        report.notes.append(
            "no local source files found (analysis based on stack trace text only)"
        )
    source_section_text = "".join(source_sections)
    budget -= estimate_tokens(source_section_text)

    # Preceding log context fills whatever budget is left.
    context_before_text = ""
    if error.context_before.strip() and budget > 100:
        cb_lines = error.context_before.splitlines()
        acc = []
        used = 0
        for line in reversed(cb_lines):  # keep the lines closest to the crash
            cost = estimate_tokens(line)
            if used + cost > budget:
                report.context_before_truncated = True
                break
            acc.append(line)
            used += cost
        acc.reverse()
        if acc:
            context_before_text = "\nLog lines immediately preceding this error:\n" + "\n".join(acc) + "\n"
            report.context_before_included = True

    full_text = header + frames_section + source_section_text + context_before_text
    if do_redact:
        full_text = redact(full_text)
    report.estimated_tokens = estimate_tokens(full_text)
    return full_text, report
