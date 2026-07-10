"""
reporter.py
===========
Report generation for visual regression testing results.

Produces three output formats:
- console  : Rich terminal output with colour-coded severity indicators
- html     : Self-contained HTML report with side-by-side comparison images,
             heatmap overlay, and structured issue table
- json     : Machine-readable output for CI/CD pipeline integration

Usage
-----
    from reporter import Reporter
    reporter = Reporter(output_dir="vrt_output")
    report = reporter.render(baseline_path, current_path, cv_result, ai_result, fmt="html")
    reporter.write(report, "report.html")
"""

from __future__ import annotations

import argparse
import io
import os
import sys

# Force UTF-8 stdout/stderr on Windows to avoid cp1252 codec errors
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass # fallback for older python versions

import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2

from image_processor import ComparisonResult
from ai_analyzer import AIAnalysisResult


# ---------------------------------------------------------------------------
# Severity colour helpers
# ---------------------------------------------------------------------------

_SEVERITY_ANSI = {
    "critical": "\033[91m",  # bright red
    "high":     "\033[31m",  # red
    "medium":   "\033[33m",  # yellow
    "low":      "\033[32m",  # green
    "none":     "\033[32m",
    "unknown":  "\033[37m",
}
_RESET = "\033[0m"
_BOLD  = "\033[1m"

_SEVERITY_HTML_COLOR = {
    "critical": "#e74c3c",
    "high":     "#e67e22",
    "medium":   "#f1c40f",
    "low":      "#2ecc71",
    "none":     "#2ecc71",
    "unknown":  "#95a5a6",
}


def _sev_badge(sev: str, html: bool = False) -> str:
    if html:
        col = _SEVERITY_HTML_COLOR.get(sev, "#95a5a6")
        return (
            f'<span style="background:{col};color:#fff;padding:2px 8px;'
            f'border-radius:12px;font-size:0.8em;font-weight:600;">'
            f'{sev.upper()}</span>'
        )
    col = _SEVERITY_ANSI.get(sev, "")
    return f"{col}{_BOLD}{sev.upper()}{_RESET}"


# ---------------------------------------------------------------------------
# Reporter class
# ---------------------------------------------------------------------------

class Reporter:
    """
    Generates formatted comparison reports.

    Parameters
    ----------
    output_dir : str
        Directory where diff images and reports will be saved.
    """

    def __init__(self, output_dir: str = "vrt_output"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def render(
        self,
        baseline_path: str,
        current_path: str,
        cv_result: ComparisonResult,
        ai_result: Optional[AIAnalysisResult],
        fmt: str = "console",
        image_paths: Optional[dict] = None,
    ) -> str:
        """Return the report as a string in the requested format."""
        dispatch = {
            "console": self._render_console,
            "html":    self._render_html,
            "json":    self._render_json,
        }
        fn = dispatch.get(fmt)
        if fn is None:
            raise ValueError(f"Unknown format: {fmt!r}. Choose from: console, html, json")
        return fn(baseline_path, current_path, cv_result, ai_result, image_paths or {})

    @staticmethod
    def write(content: str, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)

    # ------------------------------------------------------------------
    # Console renderer
    # ------------------------------------------------------------------

    def _render_console(
        self,
        baseline_path: str,
        current_path: str,
        cv_result: ComparisonResult,
        ai_result: Optional[AIAnalysisResult],
        image_paths: dict,
    ) -> str:
        W = 78
        lines = []
        lines.append("=" * W)
        lines.append(f"  {_BOLD}VISUAL REGRESSION TEST REPORT{_RESET}")
        lines.append("=" * W)
        lines.append(f"  Baseline : {baseline_path}")
        lines.append(f"  Current  : {current_path}")
        lines.append(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("-" * W)

        # Overall result
        status = f"{_BOLD}\033[32m[PASSED]{_RESET}" if cv_result.passed else f"{_BOLD}\033[31m[FAILED]{_RESET}"
        lines.append(f"\n  Result   : {status}")
        lines.append(f"  SSIM     : {cv_result.ssim_score:.4f}  (threshold >= {getattr(cv_result, '_threshold', 'configured')})")
        lines.append(f"  Changed  : {cv_result.changed_percentage:.2f}% of pixels")
        lines.append(f"  Severity : {_sev_badge(cv_result.severity)}")
        lines.append(f"  Regions  : {len(cv_result.changed_regions)} change region(s) detected")

        # OpenCV layer scores
        lines.append("\n  --- OpenCV Analysis ---")
        lines.append(f"  Feature match score  : {cv_result.feature_match_score:.4f}")
        lines.append(f"  Layout shift (ORB)   : {'YES [!]' if cv_result.layout_shift_detected else 'No'}")
        lines.append(f"  Edge diff score      : {cv_result.edge_diff_score:.4f}")
        lines.append(f"  Histogram similarity : {cv_result.histogram_similarity:.4f}")

        # Changed regions
        if cv_result.changed_regions:
            lines.append("\n  --- Changed Regions ---")
            for i, r in enumerate(cv_result.changed_regions[:10], 1):
                lines.append(f"  [{i:2d}] {_sev_badge(r.severity)}  {r.description}")

        # AI summary
        lines.append("\n  --- AI Analysis (Ollama) ---")
        if ai_result is None:
            lines.append("  (skipped — dry-run mode)")
        elif ai_result.error and not ai_result.summary:
            lines.append(f"  \033[33mWARNING: {ai_result.error}{_RESET}")
        else:
            lines.append(f"  Model   : {ai_result.model_used}")
            lines.append(f"  Summary : {ai_result.summary}")
            if ai_result.issues:
                lines.append(f"\n  Issues ({len(ai_result.issues)}):")
                for iss in ai_result.issues:
                    lines.append(f"    • [{_sev_badge(iss.severity)}] {iss.description}")
                    if iss.location:
                        lines.append(f"      Location: {iss.location}")
                    if iss.recommendation:
                        lines.append(f"      Fix:      {iss.recommendation}")
            if ai_result.recommendation:
                lines.append(f"\n  Recommendation: {ai_result.recommendation}")
            if ai_result.error:
                lines.append(f"  note: {ai_result.error}")

        # Saved artefacts
        if image_paths:
            lines.append("\n  --- Saved Artefacts ---")
            for name, path in image_paths.items():
                lines.append(f"  {name:<12}: {path}")

        lines.append("\n" + "=" * W)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # HTML renderer
    # ------------------------------------------------------------------

    def _render_html(
        self,
        baseline_path: str,
        current_path: str,
        cv_result: ComparisonResult,
        ai_result: Optional[AIAnalysisResult],
        image_paths: dict,
    ) -> str:
        def _img_tag(path: str, alt: str, style: str = "") -> str:
            try:
                with open(path, "rb") as fh:
                    b64 = base64.b64encode(fh.read()).decode()
                ext = Path(path).suffix.lstrip(".").lower()
                mime = "jpeg" if ext in ("jpg", "jpeg") else "png"
                return (
                    f'<img src="data:image/{mime};base64,{b64}" '
                    f'alt="{alt}" style="max-width:100%;border-radius:6px;{style}">'
                )
            except Exception:
                return f'<p style="color:#e74c3c">Image not found: {path}</p>'

        status_color = "#2ecc71" if cv_result.passed else "#e74c3c"
        status_text  = "PASSED ✓" if cv_result.passed else "FAILED ✗"
        sev_col      = _SEVERITY_HTML_COLOR.get(cv_result.severity, "#95a5a6")

        # Issues table rows
        issue_rows = ""
        if ai_result and ai_result.issues:
            for iss in ai_result.issues:
                col = _SEVERITY_HTML_COLOR.get(iss.severity, "#95a5a6")
                issue_rows += f"""
                <tr>
                  <td>{_sev_badge(iss.severity, html=True)}</td>
                  <td>{iss.description}</td>
                  <td>{iss.location}</td>
                  <td>{iss.recommendation}</td>
                </tr>"""
        elif cv_result.changed_regions:
            for r in cv_result.changed_regions[:15]:
                col = _SEVERITY_HTML_COLOR.get(r.severity, "#95a5a6")
                issue_rows += f"""
                <tr>
                  <td>{_sev_badge(r.severity, html=True)}</td>
                  <td>{r.description}</td>
                  <td>x={r.x}, y={r.y}</td>
                  <td>Review the annotated diff image for visual context.</td>
                </tr>"""

        ai_section = ""
        if ai_result:
            if ai_result.error and not ai_result.summary:
                ai_section = f'<p style="color:#e67e22">⚠ {ai_result.error}</p>'
            else:
                ai_section = f"""
                <div class="metric-grid" style="margin-bottom:12px;">
                  <div class="metric-card">
                    <div class="metric-label">Model</div>
                    <div class="metric-value" style="font-size:1rem;">{ai_result.model_used}</div>
                  </div>
                  <div class="metric-card">
                    <div class="metric-label">Confidence</div>
                    <div class="metric-value" style="font-size:1rem;">{ai_result.confidence}</div>
                  </div>
                  <div class="metric-card">
                    <div class="metric-label">Elapsed</div>
                    <div class="metric-value" style="font-size:1rem;">{ai_result.elapsed_seconds}s</div>
                  </div>
                </div>
                <p><strong>Summary:</strong> {ai_result.summary}</p>
                {f'<p><strong>Recommendation:</strong> {ai_result.recommendation}</p>' if ai_result.recommendation else ''}
                """
        else:
            ai_section = "<p><em>Skipped — dry-run mode active.</em></p>"

        heatmap_html   = _img_tag(image_paths.get("heatmap",   ""), "Diff heatmap") if image_paths.get("heatmap")   else "<p>N/A</p>"
        annotated_html = _img_tag(image_paths.get("annotated", ""), "Annotated diff") if image_paths.get("annotated") else "<p>N/A</p>"
        baseline_html  = _img_tag(baseline_path, "Baseline screenshot")
        current_html   = _img_tag(current_path,  "Current screenshot")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Visual Regression Test Report</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Segoe UI', system-ui, sans-serif;
      background: #0f1117; color: #e0e0e0; line-height: 1.6;
    }}
    header {{
      background: linear-gradient(135deg, #1a1f2e 0%, #16213e 50%, #0d3b6b 100%);
      padding: 40px; border-bottom: 1px solid #2d3748;
    }}
    header h1 {{ font-size: 2rem; color: #fff; font-weight: 700; }}
    header p  {{ color: #94a3b8; font-size: 0.9rem; margin-top: 6px; }}
    .badge {{
      display: inline-block; padding: 6px 18px; border-radius: 24px;
      font-weight: 700; font-size: 1.1rem; margin-top: 16px;
      background: {status_color}22; color: {status_color};
      border: 1.5px solid {status_color};
    }}
    main {{ max-width: 1400px; margin: 0 auto; padding: 40px 24px; }}
    h2 {{
      font-size: 1.1rem; font-weight: 700; color: #93c5fd;
      text-transform: uppercase; letter-spacing: 1px;
      margin: 32px 0 16px; border-bottom: 1px solid #2d3748; padding-bottom: 8px;
    }}
    .metric-grid {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px;
    }}
    .metric-card {{
      background: #1e2433; border: 1px solid #2d3748; border-radius: 12px; padding: 20px;
    }}
    .metric-label {{ font-size: 0.75rem; color: #64748b; text-transform: uppercase; letter-spacing: 1px; }}
    .metric-value {{ font-size: 1.6rem; font-weight: 700; color: #f1f5f9; margin-top: 4px; }}
    .img-grid {{
      display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px;
    }}
    .img-card {{
      background: #1e2433; border: 1px solid #2d3748; border-radius: 12px; padding: 16px;
    }}
    .img-card h3 {{ color: #94a3b8; font-size: 0.85rem; margin-bottom: 10px; text-transform: uppercase; }}
    .full-width {{ grid-column: 1/-1; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    th {{ background: #1e2433; color: #93c5fd; text-align: left; padding: 12px 14px; }}
    td {{ border-bottom: 1px solid #1e2433; padding: 10px 14px; vertical-align: top; }}
    tr:hover td {{ background: #1e2433; }}
    .ai-section {{ background: #1e2433; border: 1px solid #2d3748; border-radius: 12px; padding: 24px; }}
    .footer {{ text-align: center; color: #475569; font-size: 0.8rem; margin-top: 40px; padding: 20px; }}
  </style>
</head>
<body>
  <header>
    <h1>🔍 Visual Regression Test Report</h1>
    <p>Baseline: <code>{baseline_path}</code> &nbsp;→&nbsp; Current: <code>{current_path}</code></p>
    <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <div class="badge">{status_text}</div>
  </header>
  <main>

    <h2>📊 Metrics Overview</h2>
    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">SSIM Score</div>
        <div class="metric-value">{cv_result.ssim_score:.4f}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Changed Pixels</div>
        <div class="metric-value">{cv_result.changed_percentage:.2f}%</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Changed Regions</div>
        <div class="metric-value">{len(cv_result.changed_regions)}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Layout Shift</div>
        <div class="metric-value" style="color:{'#e74c3c' if cv_result.layout_shift_detected else '#2ecc71'}">
          {'YES' if cv_result.layout_shift_detected else 'No'}
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Edge Diff</div>
        <div class="metric-value">{cv_result.edge_diff_score:.4f}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Histogram Sim.</div>
        <div class="metric-value">{cv_result.histogram_similarity:.4f}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Severity</div>
        <div class="metric-value" style="color:{sev_col}">{cv_result.severity.upper()}</div>
      </div>
    </div>

    <h2>🖼 Screenshot Comparison</h2>
    <div class="img-grid">
      <div class="img-card"><h3>Baseline</h3>{baseline_html}</div>
      <div class="img-card"><h3>Current Deployment</h3>{current_html}</div>
      <div class="img-card full-width"><h3>Annotated Diff (Red=High, Orange=Medium, Green=Low)</h3>{annotated_html}</div>
      <div class="img-card full-width"><h3>Difference Heatmap</h3>{heatmap_html}</div>
    </div>

    <h2>🤖 AI Analysis (Ollama)</h2>
    <div class="ai-section">{ai_section}</div>

    <h2>📋 Issue Details</h2>
    <table>
      <thead>
        <tr><th>Severity</th><th>Description</th><th>Location</th><th>Recommendation</th></tr>
      </thead>
      <tbody>{issue_rows}</tbody>
    </table>

  </main>
  <div class="footer">
    Generated by Visual Regression Tester &nbsp;·&nbsp; Powered by OpenCV + Ollama (local AI)
  </div>
</body>
</html>"""
        return html

    # ------------------------------------------------------------------
    # JSON renderer
    # ------------------------------------------------------------------

    def _render_json(
        self,
        baseline_path: str,
        current_path: str,
        cv_result: ComparisonResult,
        ai_result: Optional[AIAnalysisResult],
        image_paths: dict,
    ) -> str:
        payload: dict = {
            "timestamp": datetime.now().isoformat(),
            "baseline":  baseline_path,
            "current":   current_path,
            "result": {
                "passed":   cv_result.passed,
                "severity": cv_result.severity,
            },
            "opencv_metrics": {
                "ssim_score":           cv_result.ssim_score,
                "changed_pixels_pct":   cv_result.changed_percentage,
                "total_changed_pixels": cv_result.total_changed_pixels,
                "layout_shift":         cv_result.layout_shift_detected,
                "feature_match_score":  cv_result.feature_match_score,
                "edge_diff_score":      cv_result.edge_diff_score,
                "histogram_similarity": cv_result.histogram_similarity,
            },
            "changed_regions": [
                {
                    "x": r.x, "y": r.y, "width": r.width, "height": r.height,
                    "area": r.area, "severity": r.severity, "description": r.description,
                }
                for r in cv_result.changed_regions
            ],
        }

        if ai_result:
            payload["ai_analysis"] = {
                "model":            ai_result.model_used,
                "summary":          ai_result.summary,
                "overall_severity": ai_result.overall_severity,
                "confidence":       ai_result.confidence,
                "recommendation":   ai_result.recommendation,
                "elapsed_seconds":  ai_result.elapsed_seconds,
                "error":            ai_result.error,
                "issues": [
                    {
                        "severity":       i.severity,
                        "description":    i.description,
                        "location":       i.location,
                        "recommendation": i.recommendation,
                    }
                    for i in ai_result.issues
                ],
            }
        else:
            payload["ai_analysis"] = None

        if image_paths:
            payload["artefacts"] = image_paths

        return json.dumps(payload, indent=2)
