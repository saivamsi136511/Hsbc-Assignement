"""
parsers.py
==========
Turns raw log text into structured ParsedError objects.

Design notes (why it's built this way):
- Logs come from many languages/runtimes with wildly different stack trace
  formats. Rather than one giant regex, each format gets its own small
  detector + frame parser, and there's a generic fallback for anything that
  doesn't match a known shape (custom loggers, truncated logs, etc).
- Parsing is done as a single pass over lines with a small rolling buffer,
  so it works on multi-GB log files without loading everything into memory
  (see iter_parse_file / iter_parse_lines).
- Errors are fingerprinted so that the same crash happening 500 times in a
  log (extremely common in production logs) collapses into one entry with
  an occurrence count, instead of wasting AI calls/tokens on duplicates.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Iterable, Iterator, List, Optional

# How many lines of preceding log output to keep as situational context
# for each error. Bounded so one crash doesn't vacuum up the whole file.
CONTEXT_BEFORE_LINES = 15


@dataclass
class StackFrame:
    file: str
    line: Optional[int] = None
    function: Optional[str] = None
    column: Optional[int] = None
    raw: str = ""
    code_context: Optional[str] = None  # filled in later by context_builder

    def is_likely_own_code(self, source_dir: Optional[str] = None) -> bool:
        """Heuristic: is this frame probably the user's own code, as opposed
        to a stdlib / third-party / framework frame? Used to guess the
        'offending' frame rather than just taking the top of the stack,
        which is very often inside a library, not the app's bug."""
        path = self.file or ""
        third_party_markers = (
            "site-packages", "dist-packages", "node_modules", "/usr/lib/",
            "/usr/local/lib/", ".venv", "vendor/", "<frozen", "internal/",
        )
        stdlib_java_markers = (
            "java.", "javax.", "sun.", "jdk.", "kotlin.", "scala.",
        )
        if any(m in path for m in third_party_markers):
            return False
        if self.function and any(self.function.startswith(m) for m in stdlib_java_markers):
            return False
        if source_dir and source_dir in path:
            return True
        return True


@dataclass
class ParsedError:
    error_type: str
    message: str
    frames: List[StackFrame]
    format: str                 # "python" | "java" | "node" | "go" | "generic"
    raw_block: str
    context_before: str = ""
    timestamp: Optional[str] = None
    occurrence_count: int = 1
    fingerprint: str = field(default="", repr=False)

    def __post_init__(self):
        if not self.fingerprint:
            self.fingerprint = self._compute_fingerprint()

    def _compute_fingerprint(self) -> str:
        """Groups near-identical errors together even when the message
        contains dynamic data (ids, timestamps, hex addresses), so
        'user 123 not found' and 'user 456 not found' dedupe as one issue."""
        normalized_msg = re.sub(r"[\w.\-]*\d[\w.\-]*", "#", self.message)
        top_frame = f"{self.frames[0].file}:{self.frames[0].line}" if self.frames else "?"
        key = f"{self.error_type}|{normalized_msg}|{top_frame}"
        return hashlib.sha1(key.encode("utf-8", "ignore")).hexdigest()[:12]

    def likely_offending_frame(self, source_dir: Optional[str] = None) -> Optional[StackFrame]:
        for f in self.frames:
            if f.is_likely_own_code(source_dir):
                return f
        return self.frames[0] if self.frames else None


# ---------------------------------------------------------------------------
# Format detectors. Each returns True if the given line looks like the start
# of that format's error block.
# ---------------------------------------------------------------------------

_PY_TRACEBACK_START = re.compile(r"^Traceback \(most recent call last\):\s*$")
_PY_FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>.+)$')
_PY_EXC_LINE = re.compile(r"^(?P<type>[\w.]+(?:Error|Exception|Warning))(?::\s*(?P<msg>.*))?$")

# Java exception headers come in two shapes: "Exception in thread "x" <type>: msg"
# or a bare "<type>: msg" (e.g. for "Caused by" chains flattened by some loggers).
# The bare form REQUIRES a dotted/package-qualified type name (java.lang.Foo,
# com.acme.BarException) -- this is what disambiguates it from JS/Node's bare
# "TypeError: ...", "RangeError: ..." etc., which never have a package prefix.
_JAVA_EXC_START_THREAD = re.compile(
    r'^Exception in thread "[^"]+"\s*'
    r"(?P<type>(?:[\w$]+\.)*[\w$]*(?:Exception|Error|Throwable))"
    r"(?::\s*(?P<msg>.*))?$"
)
_JAVA_EXC_START_PLAIN = re.compile(
    r"^(?P<type>(?:[\w$]+\.)+[\w$]*(?:Exception|Error|Throwable))"
    r"(?::\s*(?P<msg>.*))?$"
)
_JAVA_CAUSED_BY = re.compile(
    r"^Caused by:\s*(?P<type>(?:[\w$]+\.)*[\w$]*(?:Exception|Error|Throwable))(?::\s*(?P<msg>.*))?$"
)
_JAVA_FRAME = re.compile(r"^\s+at (?P<func>[\w$.<>]+)\((?P<loc>[^)]*)\)\s*$")


def _java_exc_start_match(line: str):
    return _JAVA_EXC_START_THREAD.match(line) or _JAVA_EXC_START_PLAIN.match(line)

_NODE_EXC_START = re.compile(
    r"^(?:Uncaught\s+)?(?P<type>[\w.]*Error)(?::\s*(?P<msg>.*))?$"
)
_NODE_FRAME_A = re.compile(
    r"^\s+at (?P<func>[^(]+) \((?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+)\)\s*$"
)
_NODE_FRAME_B = re.compile(
    r"^\s+at (?P<file>[^\s]+):(?P<line>\d+):(?P<col>\d+)\s*$"
)

_GO_PANIC_START = re.compile(r"^panic:\s*(?P<msg>.*)$")
_GO_FRAME = re.compile(r"^\s*\S+\(.*\)\s*$")
_GO_FILE_LINE = re.compile(r"^\s+(?P<file>\S+\.go):(?P<line>\d+)(?:\s+.*)?$")

_GENERIC_SIGNAL = re.compile(
    r"\b(ERROR|FATAL|CRITICAL|PANIC|EXCEPTION|Traceback|Unhandled)\b", re.IGNORECASE
)
_TIMESTAMP = re.compile(
    r"^\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\]?"
)


def _extract_timestamp(text: str) -> Optional[str]:
    m = _TIMESTAMP.search(text)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Streaming line-based parser
# ---------------------------------------------------------------------------

def iter_parse_lines(lines: Iterable[str]) -> Iterator[ParsedError]:
    """Single-pass streaming parser. Yields ParsedError objects as it finds
    them. Keeps only a small rolling buffer of recent lines in memory, so
    this scales to very large log files (called with a file iterator)."""
    buffer: List[str] = []          # rolling context-before window
    block: List[str] = []           # lines belonging to current error block
    mode: Optional[str] = None      # which parser is "in progress"
    pending_ts: Optional[str] = None

    def flush_block() -> Optional[ParsedError]:
        nonlocal block, mode
        if not block:
            mode = None
            return None
        text = "".join(block)
        result = _dispatch_parse(text, mode)
        block = []
        mode = None
        return result

    for raw_line in lines:
        line = raw_line if raw_line.endswith("\n") else raw_line + "\n"
        stripped = line.rstrip("\n")

        if mode == "python":
            block.append(line)
            if _PY_EXC_LINE.match(stripped) and not stripped.startswith((" ", "\t")):
                err = flush_block()
                if err:
                    err.context_before = "".join(buffer[-CONTEXT_BEFORE_LINES:])
                    if pending_ts:
                        err.timestamp = pending_ts
                    yield err
            continue

        if mode == "java":
            if _JAVA_FRAME.match(stripped) or _JAVA_CAUSED_BY.match(stripped) or stripped.startswith("..."):
                block.append(line)
                continue
            else:
                err = flush_block()
                if err:
                    err.context_before = "".join(buffer[-CONTEXT_BEFORE_LINES:])
                    if pending_ts:
                        err.timestamp = pending_ts
                    yield err
                # fall through: this line might start something new

        if mode == "node":
            if _NODE_FRAME_A.match(stripped) or _NODE_FRAME_B.match(stripped):
                block.append(line)
                continue
            else:
                err = flush_block()
                if err:
                    err.context_before = "".join(buffer[-CONTEXT_BEFORE_LINES:])
                    if pending_ts:
                        err.timestamp = pending_ts
                    yield err

        if mode == "go":
            if (_GO_FRAME.match(stripped) or _GO_FILE_LINE.match(stripped)
                    or stripped.startswith("goroutine") or stripped == ""):
                block.append(line)
                continue
            else:
                err = flush_block()
                if err:
                    err.context_before = "".join(buffer[-CONTEXT_BEFORE_LINES:])
                    if pending_ts:
                        err.timestamp = pending_ts
                    yield err

        # --- Not currently inside a block: look for a new one starting ---
        ts = _extract_timestamp(stripped)
        if ts:
            pending_ts = ts

        if _PY_TRACEBACK_START.match(stripped):
            mode = "python"
            block = [line]
        elif _java_exc_start_match(stripped):
            mode = "java"
            block = [line]
        elif _NODE_EXC_START.match(stripped):
            mode = "node"
            block = [line]
        elif _GO_PANIC_START.match(stripped):
            mode = "go"
            block = [line]
        else:
            buffer.append(line)

        if len(buffer) > CONTEXT_BEFORE_LINES * 4:
            buffer = buffer[-CONTEXT_BEFORE_LINES * 4:]

    # end of input: flush anything still open
    err = flush_block()
    if err:
        err.context_before = "".join(buffer[-CONTEXT_BEFORE_LINES:])
        if pending_ts:
            err.timestamp = pending_ts
        yield err


def iter_parse_file(path: str) -> Iterator[ParsedError]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        yield from iter_parse_lines(f)


# ---------------------------------------------------------------------------
# Per-format block -> ParsedError dispatch
# ---------------------------------------------------------------------------

def _dispatch_parse(text: str, mode: str) -> Optional[ParsedError]:
    if mode == "python":
        return _parse_python_block(text)
    if mode == "java":
        return _parse_java_block(text)
    if mode == "node":
        return _parse_node_block(text)
    if mode == "go":
        return _parse_go_block(text)
    return None


def _parse_python_block(text: str) -> Optional[ParsedError]:
    lines = text.splitlines()
    frames: List[StackFrame] = []
    error_type, message = "UnknownError", ""
    for line in lines:
        fm = _PY_FRAME.match(line)
        if fm:
            frames.append(StackFrame(
                file=fm.group("file"), line=int(fm.group("line")),
                function=fm.group("func"), raw=line,
            ))
            continue
        em = _PY_EXC_LINE.match(line.strip())
        if em and not line.startswith((" ", "\t")):
            error_type = em.group("type")
            message = (em.group("msg") or "").strip()
    if not frames and error_type == "UnknownError":
        return None
    return ParsedError(error_type=error_type, message=message, frames=frames,
                        format="python", raw_block=text)


def _parse_java_block(text: str) -> Optional[ParsedError]:
    lines = text.splitlines()
    frames: List[StackFrame] = []
    error_type, message = "UnknownError", ""
    first = True
    for line in lines:
        fm = _JAVA_FRAME.match(line)
        if fm:
            loc = fm.group("loc")
            file_, line_no = loc, None
            if ":" in loc:
                file_, _, line_str = loc.rpartition(":")
                if line_str.isdigit():
                    line_no = int(line_str)
            frames.append(StackFrame(
                file=file_, line=line_no, function=fm.group("func"), raw=line,
            ))
            continue
        m = _java_exc_start_match(line.strip()) if first else _JAVA_CAUSED_BY.match(line.strip())
        if m:
            error_type = m.group("type")
            message = (m.group("msg") or "").strip()
            first = False
    if not frames and error_type == "UnknownError":
        return None
    return ParsedError(error_type=error_type, message=message, frames=frames,
                        format="java", raw_block=text)


def _parse_node_block(text: str) -> Optional[ParsedError]:
    lines = text.splitlines()
    frames: List[StackFrame] = []
    error_type, message = "UnknownError", ""
    header = lines[0].strip() if lines else ""
    hm = _NODE_EXC_START.match(header)
    if hm:
        error_type = hm.group("type")
        message = (hm.group("msg") or "").strip()
    for line in lines[1:]:
        fm = _NODE_FRAME_A.match(line) or _NODE_FRAME_B.match(line)
        if fm:
            gd = fm.groupdict()
            frames.append(StackFrame(
                file=gd.get("file", ""), line=int(gd["line"]) if gd.get("line") else None,
                function=gd.get("func"), column=int(gd["col"]) if gd.get("col") else None,
                raw=line,
            ))
    if not frames and error_type == "UnknownError":
        return None
    return ParsedError(error_type=error_type, message=message, frames=frames,
                        format="node", raw_block=text)


def _parse_go_block(text: str) -> Optional[ParsedError]:
    lines = text.splitlines()
    message = ""
    m = _GO_PANIC_START.match(lines[0].strip()) if lines else None
    if m:
        message = m.group("msg").strip()
    frames: List[StackFrame] = []
    pending_func = None
    for line in lines[1:]:
        fl = _GO_FILE_LINE.match(line)
        if fl:
            frames.append(StackFrame(
                file=fl.group("file"), line=int(fl.group("line")),
                function=pending_func, raw=line,
            ))
            pending_func = None
        elif _GO_FRAME.match(line.strip()):
            pending_func = line.strip()
    if not frames and not message:
        return None
    return ParsedError(error_type="panic", message=message, frames=frames,
                        format="go", raw_block=text)


# ---------------------------------------------------------------------------
# Generic fallback: for logs that don't match any known stack-trace format.
# Groups contiguous lines that look error-ish into a block and hands the
# whole thing to the AI with no structured frames -- still useful, just
# less precise about "the" offending line.
# ---------------------------------------------------------------------------

def parse_generic(text: str) -> List[ParsedError]:
    lines = text.splitlines(keepends=True)
    results: List[ParsedError] = []
    buffer: List[str] = []
    block: List[str] = []
    in_block = False

    def flush():
        nonlocal block, in_block
        if block:
            joined = "".join(block)
            first_line = block[0].strip()
            results.append(ParsedError(
                error_type="Unrecognized",
                message=first_line[:200],
                frames=[],
                format="generic",
                raw_block=joined,
                context_before="".join(buffer[-CONTEXT_BEFORE_LINES:]),
                timestamp=_extract_timestamp(first_line),
            ))
        block = []
        in_block = False

    for line in lines:
        stripped = line.rstrip("\n")
        if _GENERIC_SIGNAL.search(stripped):
            block.append(line)
            in_block = True
        elif in_block and (stripped.startswith((" ", "\t")) or stripped == ""):
            block.append(line)
        else:
            flush()
            buffer.append(line)
        if len(buffer) > CONTEXT_BEFORE_LINES * 4:
            buffer = buffer[-CONTEXT_BEFORE_LINES * 4:]
    flush()
    return results


def parse_text(text: str) -> List[ParsedError]:
    """Convenience: parse an in-memory string (not streaming). Falls back to
    the generic matcher for any part of the text that structured parsers
    didn't claim, so nothing silently gets dropped."""
    structured = list(iter_parse_lines(text.splitlines(keepends=True)))
    if structured:
        return structured
    return parse_generic(text)


def dedupe(errors: List[ParsedError]) -> List[ParsedError]:
    """Collapse repeated occurrences of the same crash (by fingerprint),
    keeping the first occurrence's detail and a running count. Production
    logs frequently contain the same exception hundreds of times."""
    seen = {}
    order: List[str] = []
    for e in errors:
        if e.fingerprint in seen:
            seen[e.fingerprint].occurrence_count += 1
        else:
            seen[e.fingerprint] = e
            order.append(e.fingerprint)
    return [seen[fp] for fp in order]
