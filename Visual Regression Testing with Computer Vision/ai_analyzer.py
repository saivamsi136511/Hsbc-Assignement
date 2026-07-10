"""
ai_analyzer.py
==============
Ollama-based AI analysis for visual regression testing.

Replaces all paid-LLM dependencies (Anthropic / OpenAI) with a locally-running
Ollama instance, using a vision-capable model such as ``llava`` or ``moondream``
to produce a plain-English description of visual differences detected between
two screenshots.

The module is intentionally decoupled from the image-processing layer so that:
- The rest of the tool works with ``--dry-run`` and zero network traffic.
- Any Ollama vision model can be swapped in via ``--model``.
- Failures degrade gracefully — if Ollama is not running, analysis falls back
  to an OpenCV-only textual summary.

Ollama setup (one-time)
-----------------------
    # 1. Install Ollama  →  https://ollama.com/download
    # 2. Start the daemon
    ollama serve
    # 3. Pull a vision model (llava is recommended, ~4 GB)
    ollama pull llava
    # 4. Alternatives (smaller / faster):
    ollama pull moondream     # ~1.7 GB
    ollama pull llava:7b

Usage
-----
    from ai_analyzer import OllamaAnalyzer
    analyzer = OllamaAnalyzer(model="llava")
    result = analyzer.analyze(baseline_path, current_path, cv_result)
    print(result.summary)
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import requests

from image_processor import ComparisonResult


# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

DEFAULT_MODEL   = "llava"
OLLAMA_BASE_URL = "http://localhost:11434"
REQUEST_TIMEOUT = 120   # seconds — vision models can be slow on CPU


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AIIssue:
    """A single visual issue identified by the AI."""
    description: str
    severity: str = "medium"     # "low" | "medium" | "high" | "critical"
    location: str = ""           # human-readable location hint, e.g. "top navigation"
    recommendation: str = ""


@dataclass
class AIAnalysisResult:
    """Structured output from the Ollama vision model."""
    summary: str = ""
    issues: List[AIIssue] = field(default_factory=list)
    overall_severity: str = "low"
    confidence: str = "medium"
    recommendation: str = ""
    model_used: str = ""
    raw_response: str = field(default="", repr=False)
    error: Optional[str] = None
    # Token / timing metadata
    prompt_tokens: int = 0
    completion_tokens: int = 0
    elapsed_seconds: float = 0.0

    @classmethod
    def from_failure(cls, message: str) -> "AIAnalysisResult":
        return cls(
            summary="AI analysis unavailable.",
            error=message,
            overall_severity="unknown",
        )

    @classmethod
    def from_cv_only(cls, cv_result: ComparisonResult) -> "AIAnalysisResult":
        """Produce a meaningful result from OpenCV data alone (no LLM call)."""
        issue_count = len(cv_result.changed_regions)
        hi = sum(1 for r in cv_result.changed_regions if r.severity == "high")
        md = sum(1 for r in cv_result.changed_regions if r.severity == "medium")

        summary = (
            f"OpenCV analysis detected {issue_count} changed region(s) "
            f"(SSIM={cv_result.ssim_score:.4f}, "
            f"{cv_result.changed_percentage:.2f}% pixels changed). "
        )
        if cv_result.layout_shift_detected:
            summary += "A structural layout shift was detected via feature matching. "
        if hi:
            summary += f"{hi} high-severity region(s) require attention."

        sev = cv_result.severity
        issues = [
            AIIssue(
                description=r.description,
                severity=r.severity,
                location=f"x={r.x}, y={r.y}",
                recommendation="Review the changed area in the annotated diff image.",
            )
            for r in cv_result.changed_regions[:10]   # cap at 10 for readability
        ]

        return cls(
            summary=summary,
            issues=issues,
            overall_severity=sev,
            confidence="high",   # CV metrics are deterministic
            recommendation="Run with a live Ollama instance for natural-language descriptions.",
            model_used="opencv-only",
        )


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a QA engineer performing visual regression testing on web application screenshots.
You will be given a baseline screenshot (how the UI should look) and a current screenshot
(from a new deployment). Carefully identify any visual differences, layout shifts, missing
elements, or style regressions.

Respond with ONLY a single JSON object — no markdown, no prose — with exactly these keys:
{
  "summary": "2-4 sentence plain-English overview of the differences found",
  "overall_severity": "critical" | "high" | "medium" | "low" | "none",
  "confidence": "high" | "medium" | "low",
  "issues": [
    {
      "description": "what changed",
      "severity": "critical" | "high" | "medium" | "low",
      "location": "plain-English location (e.g. top navigation bar, login button)",
      "recommendation": "suggested fix or investigation step"
    }
  ],
  "recommendation": "overall next step for the development team"
}

Ground every claim in what you can see in the images. If images look identical say so.
"""


def _build_user_prompt(cv_result: ComparisonResult) -> str:
    """Attach quantitative OpenCV metrics to the vision prompt for grounding."""
    lines = [
        "Compare the two screenshots (baseline = left/first, current deployment = right/second).",
        "",
        "OpenCV pre-analysis metrics (use these to ground your findings):",
        f"  - SSIM score:          {cv_result.ssim_score:.4f}  (1.0 = identical, <0.95 = significant change)",
        f"  - Changed pixels:      {cv_result.changed_percentage:.2f}%",
        f"  - Layout shift (ORB):  {'YES — keypoints displaced >20px' if cv_result.layout_shift_detected else 'No'}",
        f"  - Edge diff score:     {cv_result.edge_diff_score:.4f}  (structural elements added/removed)",
        f"  - Colour histogram:    {cv_result.histogram_similarity:.4f}  (1.0 = same palette)",
        f"  - Changed regions:     {len(cv_result.changed_regions)} bounding box(es) identified",
    ]
    if cv_result.changed_regions:
        lines.append("  - Top regions (x,y,w,h,severity):")
        for r in cv_result.changed_regions[:5]:
            lines.append(f"      ({r.x},{r.y},{r.width},{r.height}) → {r.severity}")
    lines.append("")
    lines.append("Now describe the visual differences you can see between the two screenshots.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------

class OllamaAnalyzer:
    """
    Sends screenshots to a local Ollama vision model for AI analysis.

    Parameters
    ----------
    model : str
        Ollama model name (must be a vision-capable model, e.g. ``llava``).
    base_url : str
        Ollama API base URL (default: ``http://localhost:11434``).
    max_retries : int
        Number of retries on transient network / timeout errors.
    timeout : float
        Request timeout in seconds per attempt.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = OLLAMA_BASE_URL,
        max_retries: int = 1,
        timeout: float = REQUEST_TIMEOUT,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if the Ollama daemon is reachable."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """Return names of locally available Ollama models."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return []

    def analyze(
        self,
        baseline_path: str,
        current_path: str,
        cv_result: ComparisonResult,
    ) -> AIAnalysisResult:
        """
        Perform AI analysis using the Ollama vision model.

        Falls back to OpenCV-only analysis if Ollama is unavailable or the
        model does not support images.
        """
        if not self.is_available():
            return AIAnalysisResult.from_failure(
                f"Ollama not reachable at {self.base_url}. "
                "Start it with: ollama serve"
            )

        available = self.list_models()
        model_names = [m.split(":")[0] for m in available]
        if self.model.split(":")[0] not in model_names:
            return AIAnalysisResult.from_failure(
                f"Model '{self.model}' not found locally. "
                f"Available: {available or 'none'}. "
                f"Pull it with: ollama pull {self.model}"
            )

        try:
            baseline_b64 = _image_to_base64(baseline_path)
            current_b64  = _image_to_base64(current_path)
        except Exception as exc:
            return AIAnalysisResult.from_failure(f"Failed to encode images: {exc}")

        user_prompt = _build_user_prompt(cv_result)
        payload = {
            "model": self.model,
            "system": _SYSTEM_PROMPT,
            "prompt": user_prompt,
            "images": [baseline_b64, current_b64],
            "stream": False,
            "options": {"temperature": 0.1, "top_p": 0.9},
        }

        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            t0 = time.monotonic()
            try:
                resp = requests.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                elapsed = time.monotonic() - t0
                data = resp.json()
                raw_text = data.get("response", "")
                parsed = _parse_json_response(raw_text)
                parsed.model_used = self.model
                parsed.elapsed_seconds = round(elapsed, 2)
                parsed.prompt_tokens = data.get("prompt_eval_count", 0)
                parsed.completion_tokens = data.get("eval_count", 0)
                parsed.raw_response = raw_text
                return parsed
            except Exception as exc:
                last_err = exc
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)

        return AIAnalysisResult.from_failure(
            f"Ollama request failed after {self.max_retries + 1} attempt(s): {last_err}"
        )


# ---------------------------------------------------------------------------
# JSON response parsing
# ---------------------------------------------------------------------------

def _parse_json_response(text: str) -> AIAnalysisResult:
    """Parse the model's JSON response defensively."""
    cleaned = text.strip()

    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    # Try direct parse
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Find the first {...} blob
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return AIAnalysisResult(
                    summary=cleaned[:600],
                    error="Model returned non-JSON response; showing raw output.",
                    raw_response=text,
                )
        else:
            return AIAnalysisResult(
                summary=cleaned[:600],
                error="Model returned non-JSON response; showing raw output.",
                raw_response=text,
            )

    issues = [
        AIIssue(
            description=str(i.get("description", "")),
            severity=str(i.get("severity", "medium")),
            location=str(i.get("location", "")),
            recommendation=str(i.get("recommendation", "")),
        )
        for i in data.get("issues", [])
        if isinstance(i, dict)
    ]

    return AIAnalysisResult(
        summary=str(data.get("summary", "")),
        issues=issues,
        overall_severity=str(data.get("overall_severity", "medium")),
        confidence=str(data.get("confidence", "medium")),
        recommendation=str(data.get("recommendation", "")),
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _image_to_base64(path: str) -> str:
    """Read an image file and return a base64-encoded string."""
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("utf-8")
