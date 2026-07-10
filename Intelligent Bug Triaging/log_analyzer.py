#!/usr/bin/env python3
"""
log_analyzer.py — AI-powered crash log / stack trace root-cause analyzer.

Ingests application crash logs or stack traces, extracts structured stack
frames across several languages, manages the LLM context window for very
large logs, and asks a local/free LLM (Ollama by default) to produce a
plain-English summary, the likely offending file/line, and a suggested fix.
If no LLM is reachable, it falls back to a deterministic heuristic report
so the tool is still useful offline.

Quick start:
    ollama pull llama3.1          # one-time, see README.md
    python3 log_analyzer.py crash.log

See README.md for full usage, flags, and the list of edge cases handled.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import textwrap
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ===========================================================================
# 1. DATA MODELS
# ===========================================================================


@dataclass
class Frame:
    """A single stack frame extracted from a trace."""

    file: str
    line: Optional[int]
    function: Optional[str]
    raw: str


@dataclass
class ExceptionInfo:
    """One exception/error in a (possibly chained) crash event."""

    exc_type: str
    message: str
    frames: List[Frame] = field(default_factory=list)
    role: str = "unknown"  # "outermost" (symptom) | "innermost" (likely root cause) | "middle"


@dataclass
class CrashEvent:
    """One crash occurrence in the log, possibly with chained exceptions
    (Python 'During handling of...', Java 'Caused by:', .NET inner exceptions)."""

    format: str
    chain: List[ExceptionInfo]
    raw_text: str
    start_offset: int
    end_offset: int

    @property
    def root_cause(self) -> Optional[ExceptionInfo]:
        # Role-based, not position-based: Python's chain order (first traceback
        # = original cause) is the *opposite* of Java/C#'s (last "Caused by" /
        # inner exception = original cause), so we look up by role rather than
        # assuming a fixed index.
        for exc in self.chain:
            if exc.role == "innermost":
                return exc
        return self.chain[-1] if self.chain else None

    @property
    def primary(self) -> Optional[ExceptionInfo]:
        for exc in self.chain:
            if exc.role == "outermost":
                return exc
        return self.chain[0] if self.chain else None


# ===========================================================================
# 2. PRE-PROCESSING (encoding, ANSI codes, size limits)
# ===========================================================================

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def read_input(path: str, max_read_bytes: int = 2_000_000) -> Tuple[str, bool]:
    """Read a log file or stdin, handling: huge files (tail-read), binary/
    non-UTF8 content, and empty input. Returns (text, was_truncated)."""

    if path == "-":
        raw = sys.stdin.buffer.read()
    else:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Input path does not exist: {path}")
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_read_bytes:
                # Crashes are almost always near the end of a log; tail-read
                # instead of loading potentially gigabytes into memory.
                f.seek(size - max_read_bytes)
                raw = f.read()
                return _decode(raw), True
            raw = f.read()
    return _decode(raw), False


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    # Last resort: replace undecodable bytes rather than crashing.
    return raw.decode("utf-8", errors="replace")


# ===========================================================================
# 3. SECRET REDACTION (on by default — logs often carry tokens/PII)
# ===========================================================================

REDACTION_PATTERNS = [
    (re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|pwd)\s*[:=]\s*['\"]?[\w\-\.]{6,}"), r"\1: [REDACTED]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9\-_\.]{10,}"), "Bearer [REDACTED]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "[REDACTED_JWT]"),
    (re.compile(r"[\w\.\-]+@[\w\-]+\.[\w\.\-]+"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[REDACTED_IP]"),
]


def redact(text: str) -> str:
    for pattern, replacement in REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ===========================================================================
# 4. LANGUAGE-SPECIFIC PARSERS
#    Each parser finds crash-event boundaries and, within each, the chain of
#    exceptions plus their stack frames.
# ===========================================================================

PY_TRACEBACK_START = re.compile(r"^Traceback \(most recent call last\):\s*$", re.MULTILINE)
PY_FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>.+?)\s*$', re.MULTILINE)
PY_EXC_LINE = re.compile(r"^(?P<exc>[A-Za-z_][\w.]*(?:Error|Exception|Warning)?)\s*:\s*(?P<msg>.*)$")
PY_EXC_LINE_BARE = re.compile(r"^(?P<exc>[A-Za-z_][\w.]*)\s*$")
PY_CHAIN_PHRASE = re.compile(
    r"^(During handling of the above exception, another exception occurred:|"
    r"The above exception was the direct cause of the following exception:)\s*$",
    re.MULTILINE,
)

JAVA_START = re.compile(
    r'^(?:Exception in thread "[^"]*"\s*)?(?P<exc>[\w.$]+(?:Exception|Error))(?::\s*(?P<msg>.*))?$',
    re.MULTILINE,
)
JAVA_FRAME = re.compile(
    r"^\s*at\s+(?P<func>[\w$.<>\[\]]+)\("
    r"(?:(?P<file>[\w$.\-]+):(?P<line>\d+)|Native Method|Unknown Source)?\)\s*$",
    re.MULTILINE,
)
JAVA_CAUSED_BY = re.compile(r"^Caused by:\s*(?P<exc>[\w.$]+(?:Exception|Error))(?::\s*(?P<msg>.*))?$", re.MULTILINE)

NODE_ERR_HEADER = re.compile(r"^(?P<exc>[A-Za-z_$][\w.$]*(?:Error|Exception))(?::\s*(?P<msg>.*))?$", re.MULTILINE)
NODE_FRAME = re.compile(
    r"^\s*at\s+(?:(?P<func>.+?)\s+\()?(?P<file>[^\s()]+):(?P<line>\d+):(?P<col>\d+)\)?\s*$",
    re.MULTILINE,
)

GO_PANIC = re.compile(r"^panic:\s*(?P<msg>.*)$", re.MULTILINE)
GO_FRAME = re.compile(r"^\s*(?P<file>[\w/\.\-]+\.go):(?P<line>\d+)(?:\s+\+0x[0-9a-fA-F]+)?\s*$", re.MULTILINE)

CSHARP_START = re.compile(r"^(?:Unhandled [Ee]xception[.:]?\s*)?(?P<exc>[\w.]+Exception)(?::\s*(?P<msg>.*))?$", re.MULTILINE)
CSHARP_FRAME = re.compile(r"^\s*at\s+(?P<func>.+?)\s+in\s+(?P<file>.+?):line\s+(?P<line>\d+)\s*$", re.MULTILINE)
CSHARP_INNER = re.compile(r"^\s*--->\s*(?P<exc>[\w.]+Exception)(?::\s*(?P<msg>.*))?$", re.MULTILINE)

GENERIC_SEVERITY = re.compile(
    r"^.{0,40}?\b(?P<level>ERROR|FATAL|CRITICAL|Exception|panic|failed)\b.*$",
    re.MULTILINE | re.IGNORECASE,
)


def detect_format(text: str) -> str:
    if PY_TRACEBACK_START.search(text):
        return "python"
    if GO_PANIC.search(text) and re.search(r"goroutine \d+ \[", text):
        return "go"
    if CSHARP_FRAME.search(text):
        return "csharp"
    if JAVA_FRAME.search(text) and re.search(r"\.java:\d+\)", text):
        return "java"
    if NODE_FRAME.search(text) and re.search(r"\.(js|ts|mjs|cjs):\d+:\d+\)?", text):
        return "node"
    if GENERIC_SEVERITY.search(text):
        return "generic"
    return "unknown"


def _dedupe_frames(frames: List[Frame]) -> List[Frame]:
    """Collapse long runs of an identical repeated frame (common with deep
    recursion / stack overflows) into a single annotated entry."""
    if not frames:
        return frames
    out: List[Frame] = []
    i = 0
    while i < len(frames):
        j = i
        while j < len(frames) and frames[j] == frames[i]:
            j += 1
        run_len = j - i
        if run_len >= 4:
            f = frames[i]
            out.append(Frame(f.file, f.line, f.function, f"{f.raw}   [repeated {run_len}x]"))
        else:
            out.extend(frames[i:j])
        i = j
    return out


def parse_python(text: str) -> List[CrashEvent]:
    events: List[CrashEvent] = []
    starts = [m.start() for m in PY_TRACEBACK_START.finditer(text)]
    if not starts:
        return events
    # Group consecutive tracebacks that are linked by a chaining phrase into
    # a single crash event; otherwise each "Traceback" begins a new event.
    boundaries = starts + [len(text)]
    groups: List[Tuple[int, int]] = []
    cur_start = starts[0]
    for k in range(len(starts)):
        seg_end = boundaries[k + 1]
        between = text[boundaries[k]:seg_end]
        if k + 1 < len(starts) and not PY_CHAIN_PHRASE.search(text[boundaries[k]:starts[k + 1]]):
            groups.append((cur_start, starts[k + 1] if k + 1 < len(starts) else seg_end))
            cur_start = starts[k + 1] if k + 1 < len(starts) else seg_end
    groups.append((cur_start, len(text)))
    # simpler + more robust: just re-split by whether a chain phrase sits
    # between two tracebacks.
    groups = []
    seg_start = starts[0]
    for idx in range(len(starts)):
        nxt = starts[idx + 1] if idx + 1 < len(starts) else len(text)
        gap = text[starts[idx]:nxt]
        if idx + 1 < len(starts) and PY_CHAIN_PHRASE.search(gap):
            continue  # keep accumulating into the same event
        groups.append((seg_start, nxt))
        seg_start = nxt

    for g_start, g_end in groups:
        block = text[g_start:g_end]
        chain: List[ExceptionInfo] = []
        sub_starts = [m.start() for m in PY_TRACEBACK_START.finditer(block)]
        sub_bounds = sub_starts + [len(block)]
        for si in range(len(sub_starts)):
            sub = block[sub_starts[si]: sub_bounds[si + 1]]
            frames = [
                Frame(m.group("file"), int(m.group("line")), m.group("func"), m.group(0).strip())
                for m in PY_FRAME.finditer(sub)
            ]
            frames = _dedupe_frames(frames)
            # exception line = last non-empty line of this sub-block that
            # isn't a "File ..." line or source snippet.
            lines = [ln for ln in sub.splitlines() if ln.strip()]
            exc_type, msg = "UnknownError", ""
            for ln in reversed(lines):
                if ln.startswith("Traceback") or ln.strip().startswith("File ") or ln.startswith("  "):
                    if not (m := PY_EXC_LINE.match(ln.strip())):
                        continue
                m = PY_EXC_LINE.match(ln.strip()) or PY_EXC_LINE_BARE.match(ln.strip())
                if m:
                    exc_type = m.group("exc")
                    msg = m.groupdict().get("msg", "") or ""
                    break
            chain.append(ExceptionInfo(exc_type, msg, frames))
        if len(chain) == 1:
            chain[0].role = "innermost"  # single, un-chained exception: it IS the root cause
        elif chain:
            # Python prints the *original* exception first; anything after
            # "During handling of..."/"...direct cause of..." is a later
            # re-raise that wraps it. So, unlike Java/C#, the FIRST entry in
            # text order is the true root cause and the LAST is the symptom
            # that actually propagated out.
            chain[0].role = "innermost"
            chain[-1].role = "outermost"
            for mid in chain[1:-1]:
                mid.role = "middle"
        events.append(CrashEvent("python", chain, block, g_start, g_end))
    return events


def parse_java(text: str) -> List[CrashEvent]:
    events: List[CrashEvent] = []
    starts = [m.start() for m in JAVA_START.finditer(text) if JAVA_FRAME.search(text[m.start(): m.start() + 2000])]
    if not starts:
        return events
    bounds = starts + [len(text)]
    for idx in range(len(starts)):
        block = text[starts[idx]: bounds[idx + 1]]
        chain: List[ExceptionInfo] = []
        m0 = JAVA_START.match(block)
        causes = [m0] if m0 else []
        cause_spans = [0]
        for cm in JAVA_CAUSED_BY.finditer(block):
            causes.append(cm)
            cause_spans.append(cm.start())
        cause_spans.append(len(block))
        for ci, cm in enumerate(causes):
            sub = block[cause_spans[ci]: cause_spans[ci + 1]]
            frames = [
                Frame(m.group("file") or "?", int(m.group("line")) if m.group("line") else None, m.group("func"), m.group(0).strip())
                for m in JAVA_FRAME.finditer(sub)
            ]
            frames = _dedupe_frames(frames)
            chain.append(ExceptionInfo(cm.group("exc"), cm.group("msg") or "", frames))
        if chain:
            chain[0].role = "outermost"
            chain[-1].role = "innermost"
            for mid in chain[1:-1]:
                mid.role = "middle"
        events.append(CrashEvent("java", chain, block, starts[idx], bounds[idx + 1]))
    return events


def parse_node(text: str) -> List[CrashEvent]:
    events: List[CrashEvent] = []
    candidates = [m for m in NODE_ERR_HEADER.finditer(text) if NODE_FRAME.search(text[m.start(): m.start() + 1500])]
    if not candidates:
        return events
    starts = [m.start() for m in candidates]
    bounds = starts + [len(text)]
    for idx, m in enumerate(candidates):
        block = text[starts[idx]: bounds[idx + 1]]
        frames = [
            Frame(fm.group("file"), int(fm.group("line")), fm.group("func"), fm.group(0).strip())
            for fm in NODE_FRAME.finditer(block)
        ]
        frames = _dedupe_frames(frames)
        exc = ExceptionInfo(m.group("exc"), m.group("msg") or "", frames, role="innermost")
        events.append(CrashEvent("node", [exc], block, starts[idx], bounds[idx + 1]))
    return events


def parse_go(text: str) -> List[CrashEvent]:
    events: List[CrashEvent] = []
    starts = [m.start() for m in GO_PANIC.finditer(text)]
    if not starts:
        return events
    bounds = starts + [len(text)]
    for idx, m in enumerate(GO_PANIC.finditer(text)):
        block = text[starts[idx]: bounds[idx + 1]]
        frames = [
            Frame(fm.group("file"), int(fm.group("line")), None, fm.group(0).strip())
            for fm in GO_FRAME.finditer(block)
        ]
        frames = _dedupe_frames(frames)
        exc = ExceptionInfo("panic", m.group("msg"), frames, role="innermost")
        events.append(CrashEvent("go", [exc], block, starts[idx], bounds[idx + 1]))
    return events


def parse_csharp(text: str) -> List[CrashEvent]:
    events: List[CrashEvent] = []
    starts = [m.start() for m in CSHARP_START.finditer(text) if CSHARP_FRAME.search(text[m.start(): m.start() + 2000])]
    if not starts:
        return events
    bounds = starts + [len(text)]
    for idx in range(len(starts)):
        block = text[starts[idx]: bounds[idx + 1]]
        m0 = CSHARP_START.search(block)
        chain = []
        if m0:
            inner_matches = list(CSHARP_INNER.finditer(block))
            spans = [0] + [im.start() for im in inner_matches] + [len(block)]
            headers = [m0] + inner_matches
            for hi, hm in enumerate(headers):
                sub = block[spans[hi]: spans[hi + 1]]
                frames = [
                    Frame(fm.group("file"), int(fm.group("line")), fm.group("func"), fm.group(0).strip())
                    for fm in CSHARP_FRAME.finditer(sub)
                ]
                frames = _dedupe_frames(frames)
                chain.append(ExceptionInfo(hm.group("exc"), hm.group("msg") or "", frames))
        if chain:
            chain[0].role = "outermost"
            chain[-1].role = "innermost"
            for mid in chain[1:-1]:
                mid.role = "middle"
        events.append(CrashEvent("csharp", chain, block, starts[idx], bounds[idx + 1]))
    return events


def parse_generic(text: str) -> List[CrashEvent]:
    """Fallback for logs that don't match a known stack-trace shape: grab a
    window around each severe line (ERROR/FATAL/CRITICAL/Exception/panic)."""
    events: List[CrashEvent] = []
    lines = text.splitlines()
    hits = [i for i, ln in enumerate(lines) if GENERIC_SEVERITY.search(ln)]
    if not hits:
        return events
    # merge hits that are close together into one window
    merged: List[Tuple[int, int]] = []
    for h in hits:
        lo, hi = max(0, h - 5), min(len(lines), h + 6)
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    for lo, hi in merged:
        block = "\n".join(lines[lo:hi])
        sev_line = next((ln for ln in lines[lo:hi] if GENERIC_SEVERITY.search(ln)), block.splitlines()[0])
        exc = ExceptionInfo("Unknown", sev_line.strip(), [], role="innermost")
        events.append(CrashEvent("generic", [exc], block, lo, hi))
    return events


PARSERS = {
    "python": parse_python,
    "java": parse_java,
    "node": parse_node,
    "go": parse_go,
    "csharp": parse_csharp,
    "generic": parse_generic,
}


def parse_log(text: str) -> Tuple[str, List[CrashEvent]]:
    """Detect format and try, in order of confidence, every parser that
    could plausibly match — because real logs sometimes mix framework
    noise with the actual language-specific trace."""
    if not text.strip():
        return "unknown", []
    detected = detect_format(text)
    candidates = ["python", "java", "node", "go", "csharp", "generic"]
    order = ([detected] if detected in candidates else []) + [f for f in candidates if f != detected]
    for fmt in order:
        events = PARSERS[fmt](text)
        if events:
            return fmt, events
    return "unknown", []


# ===========================================================================
# 5. CONTEXT WINDOW MANAGEMENT
#    Local models often run with small (4k-8k token) context windows. We
#    build a compact, information-dense context instead of dumping the raw
#    log, and we never silently exceed the budget.
# ===========================================================================


@dataclass
class BuiltContext:
    text: str
    truncated: bool
    original_chars: int
    final_chars: int


def actual_frame(exc: ExceptionInfo, fmt: str) -> Optional[Frame]:
    """Return the frame closest to where the error actually occurred.
    IMPORTANT: stack-trace frame ordering is NOT universal across languages.
    Python traceback docs literally say "most recent call last" — the File
    line at the *bottom* is where the exception was actually raised, with
    earlier lines being callers further up the stack. Java, Node.js, Go, and
    C# do the opposite: the *first* "at ..." line is the innermost/actual
    failure point, and later lines walk back up to the entry point. Treating
    them the same way silently points at the wrong line."""
    if not exc.frames:
        return None
    if fmt == "python":
        return exc.frames[-1]
    return exc.frames[0]


def normalize_frames_most_specific_first(frames: List[Frame], fmt: str) -> List[Frame]:
    """For display/prompting, always show frames with the most-specific
    (actual failure point) frame first, regardless of the source language's
    native ordering convention — this avoids confusing smaller LLMs that
    don't reliably know each language's convention."""
    if fmt == "python":
        return list(reversed(frames))
    return frames


def _format_frames(frames: List[Frame], max_frames: int = 12) -> str:
    if not frames:
        return "    (no stack frames captured)"
    if len(frames) <= max_frames:
        shown = frames
        omitted_note = ""
    else:
        head = frames[: max_frames // 2]
        tail = frames[-(max_frames // 2):]
        shown = head + tail
        omitted_note = f"\n    ... {len(frames) - max_frames} frame(s) omitted ...\n"
    lines = []
    for i, f in enumerate(shown):
        if omitted_note and i == max_frames // 2:
            lines.append(omitted_note.strip("\n"))
        loc = f.file + (f":{f.line}" if f.line else "")
        fn = f" in {f.function}" if f.function else ""
        lines.append(f"    {loc}{fn}")
    return "\n".join(lines)


def build_llm_context(event: CrashEvent, max_chars: int = 6000) -> BuiltContext:
    """Turn a parsed CrashEvent into a compact, labeled block for the LLM
    prompt. Falls back to a truncated raw-text window if parsing found
    nothing structured (e.g. genuinely unknown log formats)."""
    original_chars = len(event.raw_text)

    if not event.chain:
        raw = event.raw_text
        if len(raw) > max_chars:
            head = raw[: max_chars // 2]
            tail = raw[-(max_chars // 2):]
            raw = head + f"\n... [{len(event.raw_text) - max_chars} characters omitted] ...\n" + tail
            return BuiltContext(raw, True, original_chars, len(raw))
        return BuiltContext(raw, False, original_chars, len(raw))

    sections = []
    for exc in event.chain:
        label = {
            "outermost": "SYMPTOM (outermost / first reported exception)",
            "innermost": "LIKELY ROOT CAUSE (innermost exception in the chain)",
            "middle": "INTERMEDIATE (chained exception)",
            "unknown": "EXCEPTION",
        }[exc.role]
        display_frames = normalize_frames_most_specific_first(exc.frames, event.format)
        block = (
            f"[{label}]\n"
            f"  Type: {exc.exc_type}\n"
            f"  Message: {exc.message}\n"
            f"  Stack frames (ordered MOST SPECIFIC FIRST — the first frame below is where this\n"
            f"  exception actually occurred; later frames are its callers):\n"
            f"{_format_frames(display_frames)}"
        )
        sections.append(block)

    text = "\n\n".join(sections)
    truncated = False
    if len(text) > max_chars:
        # Reduce frames shown per exception further until it fits, rather
        # than hard-truncating mid-sentence.
        for max_frames in (8, 5, 3, 1):
            sections = []
            for exc in event.chain:
                label = {
                    "outermost": "SYMPTOM (outermost / first reported exception)",
                    "innermost": "LIKELY ROOT CAUSE (innermost exception in the chain)",
                    "middle": "INTERMEDIATE (chained exception)",
                    "unknown": "EXCEPTION",
                }[exc.role]
                display_frames = normalize_frames_most_specific_first(exc.frames, event.format)
                block = (
                    f"[{label}]\n  Type: {exc.exc_type}\n  Message: {exc.message}\n"
                    f"  Stack frames (most specific first):\n{_format_frames(display_frames, max_frames)}"
                )
                sections.append(block)
            text = "\n\n".join(sections)
            if len(text) <= max_chars:
                truncated = True
                break
        else:
            text = text[:max_chars]
            truncated = True

    return BuiltContext(text, truncated, original_chars, len(text))


def all_known_locations(event: CrashEvent) -> List[Tuple[str, Optional[int]]]:
    """Every (file, line) pair we actually extracted — used to verify the
    LLM didn't hallucinate a location outside the evidence provided."""
    locs = []
    for exc in event.chain:
        for f in exc.frames:
            locs.append((f.file, f.line))
    return locs


# ===========================================================================
# 6. LLM CLIENT — Ollama (free, local) by default, with a deterministic
#    heuristic fallback when no LLM is reachable.
# ===========================================================================

REPORT_SCHEMA_HINT = """Respond with ONLY a single JSON object (no markdown fences, no prose
before or after) with exactly these keys:
{
  "plain_english_summary": "2-4 sentences a non-expert could understand",
  "error_type": "the exception/error class or category",
  "root_cause_explanation": "why this actually happened, referencing the chain if present",
  "offending_file": "the single most likely file path from the evidence, or null",
  "offending_line": "the line number (integer) from the evidence, or null",
  "offending_function": "function/method name from the evidence, or null",
  "confidence": "high | medium | low",
  "suggested_fix": "a concrete code/config change to fix the root cause",
  "workaround": "a short-term mitigation if a real fix isn't immediately possible",
  "category": "one of: null_reference, index_out_of_bounds, type_error, io_or_network,\
 config_or_env, concurrency, resource_exhaustion, logic_error, dependency, unknown",
  "severity": "critical | high | medium | low"
}
Only reference files/lines that literally appear in the evidence below. If you are not
sure of the exact file or line, set them to null rather than guessing."""


SYSTEM_PROMPT = (
    "You are a senior software engineer performing root-cause analysis on a crash log. "
    "You will be given a structured extraction of the exception chain and stack frames. "
    "Be precise, ground every claim in the evidence given, and never invent file paths, "
    "line numbers, or function names that are not present in the evidence."
)


class LLMUnavailable(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1", timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _post(self, path: str, payload: dict, retries: int = 2) -> dict:
        data = json.dumps(payload).encode("utf-8")
        last_err: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(
                    f"{self.base_url}{path}", data=data, headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                if e.code == 404 or "not found" in body.lower():
                    raise LLMUnavailable(
                        f"Model '{self.model}' isn't pulled in Ollama. Run: ollama pull {self.model}"
                    ) from e
                last_err = e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last_err = e
            time.sleep(1.5 * (attempt + 1))
        raise LLMUnavailable(f"Could not reach Ollama at {self.base_url}: {last_err}")

    def analyze(self, context_text: str, event: CrashEvent) -> Dict[str, Any]:
        user_prompt = (
            f"Log format detected: {event.format}\n\n"
            f"Evidence extracted from the crash log:\n{context_text}\n\n"
            f"{REPORT_SCHEMA_HINT}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
        result = self._post("/api/chat", payload)
        content = result.get("message", {}).get("content", "")
        return _parse_llm_json(content)


class OpenAICompatClient:
    """Optional: talk to any OpenAI-compatible endpoint (LM Studio, vLLM,
    text-generation-webui, or real OpenAI) using the same interface, in
    case Ollama isn't the person's local server of choice."""

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/models")
            if self.api_key:
                req.add_header("Authorization", f"Bearer {self.api_key}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def analyze(self, context_text: str, event: CrashEvent) -> Dict[str, Any]:
        user_prompt = (
            f"Log format detected: {event.format}\n\nEvidence:\n{context_text}\n\n{REPORT_SCHEMA_HINT}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=data, headers={"Content-Type": "application/json"}
        )
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise LLMUnavailable(f"Could not reach {self.base_url}: {e}")
        content = result["choices"][0]["message"]["content"]
        return _parse_llm_json(content)


def _parse_llm_json(content: str) -> Dict[str, Any]:
    """LLMs (especially smaller local ones) sometimes wrap JSON in markdown
    fences or add stray preamble even when asked not to. Recover gracefully."""
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{.*\}", content, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass
    # Total failure: surface the raw text so the user isn't left with nothing.
    return {
        "plain_english_summary": content[:800] or "The model returned no usable content.",
        "error_type": "unknown",
        "root_cause_explanation": "The LLM response could not be parsed as JSON; showing raw output.",
        "offending_file": None,
        "offending_line": None,
        "offending_function": None,
        "confidence": "low",
        "suggested_fix": "Re-run with a different/larger model — the response was malformed.",
        "workaround": "",
        "category": "unknown",
        "severity": "medium",
        "_parse_error": True,
    }


# ---------------------------------------------------------------------------
# Heuristic (no-LLM) fallback — deterministic, works fully offline.
# ---------------------------------------------------------------------------

HEURISTIC_ADVICE = {
    "nullpointerexception": ("Null reference dereferenced.", "Add a null check before use, or use Optional/`?.` "
                             "safe-navigation; validate that the producing call can't return null."),
    "nullreferenceexception": ("Null reference dereferenced.", "Add a null check before use, or use `?.`/null-"
                                "coalescing; verify the object is initialized before this code path runs."),
    "typeerror": ("A value was used with an incompatible type/shape.", "Log the value's actual type at this "
                  "point and add a type/None check before the operation."),
    "keyerror": ("A dict/map key was missing.", "Use `.get(key, default)` or check `key in dict` before access."),
    "indexerror": ("A sequence was indexed out of bounds.", "Validate the length/bounds before indexing, or use "
                   "safe slicing."),
    "indexoutofrangeexception": ("A collection was indexed out of bounds.", "Validate bounds before indexing."),
    "attributeerror": ("An attribute/method doesn't exist on this object.", "Check the object's actual type/None-"
                       "ness before the attribute access; a prior call may have returned something unexpected."),
    "connectionerror": ("A network connection failed.", "Add retry logic with backoff and verify the remote "
                        "service/host and port/firewall rules."),
    "timeouterror": ("An operation exceeded its time budget.", "Increase the timeout if justified, and/or "
                     "investigate why the dependency is slow (add tracing)."),
    "outofmemoryerror": ("The process ran out of heap memory.", "Profile memory usage, look for unbounded caches/"
                         "collections, and consider increasing heap size as a short-term mitigation."),
    "arithmeticexception": ("An arithmetic operation failed (e.g. divide by zero).", "Guard the denominator/operand "
                            "and validate inputs before the calculation."),
    "filenotfounderror": ("A required file/path was missing.", "Verify the path is correct for this environment "
                          "and that the file is deployed/mounted before startup."),
    "panic": ("A Go panic occurred, typically from a nil dereference, out-of-range index, or explicit panic() call.",
              "Add bounds/nil checks near the reported frame, or wrap the call with recover() at an appropriate "
              "boundary."),
}


def heuristic_report(event: CrashEvent) -> Dict[str, Any]:
    root = event.root_cause
    if not root:
        return {
            "plain_english_summary": "No structured exception could be extracted from this log.",
            "error_type": "unknown",
            "root_cause_explanation": "The parser did not find a recognizable stack trace or severity marker.",
            "offending_file": None, "offending_line": None, "offending_function": None,
            "confidence": "low", "suggested_fix": "Provide a larger excerpt around the failure, or try a "
            "different --which selection.", "workaround": "", "category": "unknown", "severity": "medium",
            "_heuristic": True,
        }
    key = root.exc_type.split(".")[-1].lower()
    advice = HEURISTIC_ADVICE.get(key)
    top_frame = actual_frame(root, event.format)
    summary = f"A {root.exc_type} occurred" + (f": {root.message}" if root.message else "") + "."
    if advice:
        summary += " " + advice[0]
    return {
        "plain_english_summary": summary,
        "error_type": root.exc_type,
        "root_cause_explanation": advice[0] if advice else "No built-in heuristic for this error type; the "
        "innermost frame below is the best available lead without an LLM.",
        "offending_file": top_frame.file if top_frame else None,
        "offending_line": top_frame.line if top_frame else None,
        "offending_function": top_frame.function if top_frame else None,
        "confidence": "medium" if (advice and top_frame) else "low",
        "suggested_fix": advice[1] if advice else "Inspect the innermost frame below and check the operation "
        "performed at that line against the error message.",
        "workaround": "Add error handling / a guard clause around the offending call to fail more gracefully.",
        "category": "unknown",
        "severity": "high" if len(event.chain) > 1 else "medium",
        "_heuristic": True,
    }


# ===========================================================================
# 7. REPORT VALIDATION & FORMATTING
# ===========================================================================


def validate_report(report: Dict[str, Any], event: CrashEvent) -> Dict[str, Any]:
    """Cross-check the model's claimed file/line against evidence we actually
    extracted, so hallucinated locations are flagged rather than trusted."""
    known = all_known_locations(event)
    known_files = {f for f, _ in known}
    file = report.get("offending_file")
    line = report.get("offending_line")
    verified = False
    if file:
        if any(file == f or file.endswith(f) or f.endswith(file) for f in known_files):
            verified = True
            if line is not None:
                matching_lines = {ln for f, ln in known if f == file or file.endswith(f) or f.endswith(file)}
                verified = line in matching_lines or line is None
    report["_verified_against_evidence"] = verified
    if file and not verified:
        report["_verification_note"] = (
            "This file/line was not found among the extracted stack frames — treat as a "
            "hypothesis, not a confirmed location."
        )
    return report


def format_text_report(report: Dict[str, Any], event: CrashEvent, ctx: BuiltContext, source: str) -> str:
    lines = []
    W = 78
    lines.append("=" * W)
    lines.append(" CRASH LOG ANALYSIS REPORT".ljust(W - 1) + " ")
    lines.append("=" * W)
    lines.append(f"Detected format : {event.format}")
    lines.append(f"Analysis source : {source}")
    if ctx.truncated:
        lines.append(f"Note            : context truncated for the LLM ({ctx.original_chars} -> "
                      f"{ctx.final_chars} chars) to fit the model's window")
    lines.append("-" * W)
    lines.append("SUMMARY")
    lines.append(textwrap.fill(report.get("plain_english_summary", ""), W))
    lines.append("")
    lines.append(f"Error type : {report.get('error_type')}")
    lines.append(f"Category   : {report.get('category')}")
    lines.append(f"Severity   : {report.get('severity')}")
    lines.append(f"Confidence : {report.get('confidence')}")
    lines.append("")
    lines.append("ROOT CAUSE")
    lines.append(textwrap.fill(report.get("root_cause_explanation", ""), W))
    lines.append("")
    loc_bits = []
    if report.get("offending_file"):
        loc_bits.append(f"{report['offending_file']}"
                         + (f":{report['offending_line']}" if report.get("offending_line") else ""))
    if report.get("offending_function"):
        loc_bits.append(f"in {report['offending_function']}()")
    verified_tag = ""
    if "offending_file" in report and report.get("offending_file"):
        verified_tag = "  [VERIFIED]" if report.get("_verified_against_evidence") else "  [UNVERIFIED — hypothesis]"
    lines.append("LIKELY OFFENDING LOCATION")
    lines.append("  " + (" ".join(loc_bits) if loc_bits else "unknown") + verified_tag)
    if report.get("_verification_note"):
        lines.append("  " + report["_verification_note"])
    lines.append("")
    lines.append("SUGGESTED FIX")
    lines.append(textwrap.fill(report.get("suggested_fix", ""), W))
    lines.append("")
    lines.append("WORKAROUND (short-term)")
    lines.append(textwrap.fill(report.get("workaround", "") or "(none suggested)", W))
    lines.append("=" * W)
    return "\n".join(lines)


def format_markdown_report(report: Dict[str, Any], event: CrashEvent, ctx: BuiltContext, source: str) -> str:
    verified_tag = ""
    if report.get("offending_file"):
        verified_tag = "✅ verified against extracted frames" if report.get("_verified_against_evidence") \
            else "⚠️ unverified — not found in extracted frames"
    loc = report.get("offending_file") or "unknown"
    if report.get("offending_line"):
        loc += f":{report['offending_line']}"
    md = f"""# Crash Log Analysis Report

**Detected format:** `{event.format}` &nbsp;|&nbsp; **Analysis source:** {source}

## Summary
{report.get('plain_english_summary', '')}

| Field | Value |
|---|---|
| Error type | `{report.get('error_type')}` |
| Category | {report.get('category')} |
| Severity | {report.get('severity')} |
| Confidence | {report.get('confidence')} |

## Root Cause
{report.get('root_cause_explanation', '')}

## Likely Offending Location
`{loc}` {f"in `{report['offending_function']}`" if report.get('offending_function') else ''}
{verified_tag}
{report.get('_verification_note', '')}

## Suggested Fix
{report.get('suggested_fix', '')}

## Workaround
{report.get('workaround') or '_(none suggested)_'}
"""
    if ctx.truncated:
        md += f"\n> ⚠️ Context was truncated for the LLM's window ({ctx.original_chars} → {ctx.final_chars} chars).\n"
    return md


# ===========================================================================
# 8. ORCHESTRATION
# ===========================================================================


def select_events(events: List[CrashEvent], which: str) -> List[CrashEvent]:
    if not events:
        return []
    if which == "all":
        return events
    if which == "first":
        return [events[0]]
    return [events[-1]]  # "last" (default) — most recent crash is usually most relevant


def analyze_event(
    event: CrashEvent,
    client,
    max_context_chars: int,
    force_heuristic: bool,
    strict_llm: bool,
) -> Tuple[Dict[str, Any], BuiltContext, str]:
    ctx = build_llm_context(event, max_context_chars)
    source = "heuristic (no LLM)"
    if not force_heuristic and client is not None:
        try:
            report = client.analyze(ctx.text, event)
            source = f"LLM ({getattr(client, 'model', 'unknown model')})"
        except LLMUnavailable as e:
            if strict_llm:
                raise
            sys.stderr.write(f"[warn] LLM unavailable, falling back to heuristic analysis: {e}\n")
            report = heuristic_report(event)
    else:
        report = heuristic_report(event)
    report = validate_report(report, event)
    return report, ctx, source


def gather_input_paths(input_path: str) -> List[str]:
    if input_path == "-":
        return ["-"]
    if os.path.isdir(input_path):
        paths = sorted(glob.glob(os.path.join(input_path, "*.log")) + glob.glob(os.path.join(input_path, "*.txt")))
        if not paths:
            raise FileNotFoundError(f"No .log/.txt files found in directory: {input_path}")
        return paths
    return [input_path]


# ===========================================================================
# 9. CLI
# ===========================================================================


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="AI-powered crash log / stack trace root-cause analyzer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 log_analyzer.py crash.log
  cat crash.log | python3 log_analyzer.py -
  python3 log_analyzer.py ./logs_dir --output markdown --save report.md
  python3 log_analyzer.py crash.log --model qwen2.5-coder:7b --which all
  python3 log_analyzer.py crash.log --provider none      # offline heuristic mode
""",
    )
    p.add_argument("input", help="Path to a log file, a directory of *.log/*.txt files, or '-' for stdin")
    p.add_argument("--provider", choices=["ollama", "openai", "none"], default="ollama",
                   help="LLM backend. 'none' skips the LLM and only runs the heuristic analyzer. Default: ollama")
    p.add_argument("--model", default="llama3.1", help="Model name (default: llama3.1; try qwen2.5-coder:7b or "
                   "deepseek-coder-v2 for better code-aware results)")
    p.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama base URL")
    p.add_argument("--api-base", default=None, help="Base URL for --provider openai (any OpenAI-compatible server)")
    p.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", ""), help="API key for --provider openai")
    p.add_argument("--timeout", type=int, default=60, help="LLM request timeout in seconds (default: 60)")
    p.add_argument("--strict-llm", action="store_true", help="Error out instead of silently falling back to the "
                   "heuristic analyzer when the LLM is unreachable")
    p.add_argument("--max-context-chars", type=int, default=6000, help="Max characters of evidence sent to the "
                   "LLM per crash event (default: 6000, ~1500 tokens)")
    p.add_argument("--max-read-bytes", type=int, default=2_000_000, help="For large files, only the last N bytes "
                   "are read (crashes are usually near the end). Default: 2,000,000")
    p.add_argument("--which", choices=["last", "first", "all"], default="last", help="Which crash event(s) to "
                   "analyze when a log contains multiple. Default: last (most recent)")
    p.add_argument("--output", choices=["text", "json", "markdown"], default="text", help="Report format")
    p.add_argument("--save", default=None, help="Write the report to this path in addition to printing it")
    p.add_argument("--no-redact", action="store_true", help="Disable automatic redaction of secrets/emails/IPs "
                   "before sending log content to the LLM (redaction is ON by default)")
    p.add_argument("--verbose", action="store_true", help="Print extra diagnostic info to stderr")
    return p


def make_client(args):
    if args.provider == "none":
        return None
    if args.provider == "ollama":
        client = OllamaClient(base_url=args.ollama_url, model=args.model, timeout=args.timeout)
    else:
        if not args.api_base:
            sys.stderr.write("[error] --provider openai requires --api-base\n")
            sys.exit(2)
        client = OpenAICompatClient(base_url=args.api_base, model=args.model, api_key=args.api_key, timeout=args.timeout)
    if not client.is_available():
        sys.stderr.write(
            f"[warn] Could not reach {args.provider} at "
            f"{getattr(client, 'base_url', '?')} — will fall back to heuristic analysis "
            f"unless --strict-llm is set.\n"
        )
        if args.provider == "ollama":
            sys.stderr.write("        Is Ollama running? Try: ollama serve   (and: ollama pull " + args.model + ")\n")
    return client


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        paths = gather_input_paths(args.input)
    except FileNotFoundError as e:
        sys.stderr.write(f"[error] {e}\n")
        return 1

    client = make_client(args)
    any_output = False

    for path in paths:
        try:
            text, was_tail_truncated = read_input(path, args.max_read_bytes)
        except FileNotFoundError as e:
            sys.stderr.write(f"[error] {e}\n")
            continue

        if not text.strip():
            sys.stderr.write(f"[warn] {path}: empty input, skipping.\n")
            continue

        text = strip_ansi(text)
        if not args.no_redact:
            text = redact(text)
        if was_tail_truncated and args.verbose:
            sys.stderr.write(f"[info] {path}: file exceeded --max-read-bytes; analyzing the tail of the file.\n")

        fmt, events = parse_log(text)
        if not events:
            sys.stderr.write(
                f"[warn] {path}: no recognizable exception/stack trace found "
                f"(detected format: {fmt}). Nothing to analyze.\n"
            )
            continue

        if args.verbose:
            sys.stderr.write(f"[info] {path}: detected '{fmt}', found {len(events)} crash event(s).\n")

        chosen = select_events(events, args.which)
        outputs = []
        for i, event in enumerate(chosen):
            try:
                report, ctx, source = analyze_event(
                    event, client, args.max_context_chars,
                    force_heuristic=(args.provider == "none"),
                    strict_llm=args.strict_llm,
                )
            except LLMUnavailable as e:
                sys.stderr.write(f"[error] {path} (event {i+1}): {e}\n")
                continue

            if args.output == "json":
                payload = {
                    "file": path, "event_index": i, "format": event.format,
                    "analysis_source": source, "context_truncated": ctx.truncated,
                    "report": report,
                }
                outputs.append(json.dumps(payload, indent=2))
            elif args.output == "markdown":
                outputs.append(format_markdown_report(report, event, ctx, source))
            else:
                outputs.append(format_text_report(report, event, ctx, source))

        if not outputs:
            continue

        final_text = ("\n\n" + "-" * 78 + "\n\n").join(outputs)
        print(final_text)
        any_output = True

        if args.save:
            mode = "a" if len(paths) > 1 else "w"
            with open(args.save, mode, encoding="utf-8") as f:
                f.write(final_text + "\n")

    if args.save and any_output:
        print(f"\n[saved report to {args.save}]", file=sys.stderr)

    return 0 if any_output else 1


if __name__ == "__main__":
    sys.exit(main())
