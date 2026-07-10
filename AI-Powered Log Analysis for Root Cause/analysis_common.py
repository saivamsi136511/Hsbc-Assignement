"""
analysis_common.py
===================
Backend-agnostic pieces shared by every AI backend (Anthropic API, Ollama,
and any future one): the result schema, the system prompt, and the
defensive JSON-parsing logic. Keeping this separate means adding a new
backend is just "call a model, hand the text to parse_json_response()" --
the report rendering and CLI never need to know which backend produced it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

SYSTEM_PROMPT = """You are a senior software engineer doing root-cause analysis on a \
production crash. You will be given: the error type/message, a (possibly truncated) \
stack trace, source code near the likely offending line if available, and log lines \
that preceded the crash.

Respond with ONLY a single JSON object (no prose, no markdown fences) with exactly \
these keys:
{
  "summary": "1-3 sentences explaining the error in plain English for someone who didn't write this code",
  "likely_file": "the file you believe is the actual root cause (best guess if ambiguous)",
  "likely_line": "the line number as a string, or null if unclear",
  "root_cause": "your best hypothesis for WHY this happened, grounded in the evidence given",
  "confidence": "high" | "medium" | "low",
  "suggested_fix": "a concrete code-level fix, or specific next debugging step if a fix isn't determinable from the given context",
  "workaround": "a short-term mitigation if applicable, or null",
  "severity": "critical" | "high" | "medium" | "low"
}

Ground every claim in the provided evidence. If the context doesn't contain enough \
information to be sure, say so plainly in the relevant field and lower your confidence \
rather than guessing at specifics you can't support. Smaller/local models: keep every \
field short and do not add any text outside the JSON object -- it must parse as JSON."""


@dataclass
class AnalysisResult:
    summary: str = ""
    likely_file: str = ""
    likely_line: Optional[str] = None
    root_cause: str = ""
    confidence: str = "low"
    suggested_fix: str = ""
    workaround: Optional[str] = None
    severity: str = "medium"
    raw_response: str = field(default="", repr=False)
    error: Optional[str] = None       # set if the API call / parse failed
    input_tokens: int = 0
    output_tokens: int = 0
    backend: str = ""
    model: str = ""

    @classmethod
    def from_failure(cls, message: str, backend: str = "", model: str = "") -> "AnalysisResult":
        return cls(summary="Analysis unavailable.", error=message, backend=backend, model=model)


def strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def parse_json_response(text: str, backend: str = "", model: str = "") -> AnalysisResult:
    """Defensively parse a model's response into an AnalysisResult. Handles
    clean JSON, JSON wrapped in markdown fences, and JSON with stray prose
    around it (common with smaller/local models that don't always follow
    "JSON only" instructions as reliably as larger hosted models)."""
    cleaned = strip_code_fences(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                return AnalysisResult(
                    summary=cleaned[:500],
                    error="Model did not return valid JSON; showing raw output.",
                    raw_response=text, backend=backend, model=model,
                )
        else:
            return AnalysisResult(
                summary=cleaned[:500],
                error="Model did not return valid JSON; showing raw output.",
                raw_response=text, backend=backend, model=model,
            )
    return AnalysisResult(
        summary=str(data.get("summary", "")),
        likely_file=str(data.get("likely_file", "")),
        likely_line=(str(data["likely_line"]) if data.get("likely_line") not in (None, "null") else None),
        root_cause=str(data.get("root_cause", "")),
        confidence=str(data.get("confidence", "low")),
        suggested_fix=str(data.get("suggested_fix", "")),
        workaround=(str(data["workaround"]) if data.get("workaround") not in (None, "null") else None),
        severity=str(data.get("severity", "medium")),
        raw_response=text,
        backend=backend,
        model=model,
    )
