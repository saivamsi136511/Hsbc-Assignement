# Visual Regression Testing with Computer Vision

An AI-powered visual regression testing tool that compares baseline screenshots with new deployment screenshots using **OpenCV** computer vision and a **local Ollama** language model — no paid APIs, no cloud dependencies.

Instead of brittle pixel-by-pixel comparison, the tool uses a **multi-layer structural analysis** to intelligently detect real regressions while filtering out false positives from anti-aliasing, sub-pixel rendering differences, and dynamic content.

---

## Quick Start

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. (Optional) Install Ollama for AI-powered analysis
#    Download: https://ollama.com/download
ollama serve                  # start the daemon
ollama pull llava             # pull a vision model (~4 GB)

# 3. Run against sample screenshots (dry-run — no Ollama needed)
python visual_regressor.py \
    --baseline sample_screenshots/baseline.png \
    --current  sample_screenshots/new_deployment.png \
    --dry-run --verbose

# 4. Full run with Ollama AI analysis and HTML report
python visual_regressor.py \
    --baseline sample_screenshots/baseline.png \
    --current  sample_screenshots/new_deployment.png \
    --format html --output report.html --verbose

# 5. CI/CD JSON output (exits 1 on failure)
python visual_regressor.py \
    --baseline baseline.png --current current.png \
    --threshold 0.90 --format json --output result.json
```

---

## What It Actually Does

### 1. Multi-Layer OpenCV Analysis (No Pixel-by-Pixel!)

| Layer | Method | What it catches |
|-------|--------|----------------|
| **Structural** | SSIM (Structural Similarity Index) | Overall visual quality regression |
| **Feature** | ORB keypoint matching | Layout shifts — elements moved >20px |
| **Edge** | Canny edge map diff | Missing / newly added structural elements |
| **Region** | Contour detection + dilation | Groups changed pixels into meaningful bounding boxes |
| **Colour** | Per-channel histogram correlation | Stylesheet / theme / palette changes |

### 2. Intelligent False Positive Reduction

- **Minimum area filter** — changes smaller than `--min-change-area` pixels are ignored (eliminates anti-aliasing noise)
- **Gaussian blur pre-processing** — reduces sub-pixel rendering differences between browsers
- **Dynamic region masking** — `--ignore-region X,Y,W,H` blacks out timestamps, carousels, ads before comparison
- **Severity grading** — each changed region is classified as `low / medium / high` based on pixel intensity delta

### 3. Local AI Analysis via Ollama

The tool sends the diff heatmap and both screenshots to a **locally-running Ollama vision model** (e.g. `llava`, `moondream`) along with quantitative OpenCV metrics as grounding context. The model produces:

- A plain-English summary of what changed and why it matters
- Per-issue descriptions with location and severity
- An actionable recommendation for the development team

**Zero data leaves your machine** — no Anthropic, no OpenAI, no cloud calls.

### 4. Report Formats

| Format | Description |
|--------|-------------|
| `console` | Colour-coded terminal report with severity badges |
| `html` | Self-contained dark-themed HTML with embedded side-by-side comparison, heatmap, and issue table |
| `json` | Machine-readable output for CI/CD pipeline integration |

---

## CLI Reference

```
python visual_regressor.py --baseline PATH --current PATH [options]

Required:
  --baseline PATH         Reference screenshot (how the UI should look)
  --current  PATH         New deployment screenshot

AI settings:
  --model MODEL           Ollama vision model (default: llava)
  --ollama-url URL        Ollama API base URL (default: http://localhost:11434)

Comparison settings:
  --threshold FLOAT       SSIM pass/fail threshold, 0–1 (default: 0.95)
  --min-change-area INT   Min changed-region area in px (default: 100)
  --ignore-region X,Y,W,H Ignore a rectangle (dynamic content). Repeatable.

Output:
  -o, --output FILE       Write report to file instead of stdout
  --format {console,html,json}  Output format (default: console)
  --output-dir DIR        Directory for diff images (default: vrt_output)

Mode:
  --dry-run               OpenCV analysis only, skip Ollama calls
  --no-save-images        Don't save diff/heatmap/annotated images
  -v, --verbose           Progress messages to stderr
```

### Exit Codes (for CI/CD)

| Code | Meaning |
|------|---------|
| `0` | Test passed (SSIM ≥ threshold) |
| `1` | Test failed or error occurred |

---

## Ollama Setup

```bash
# Install Ollama (Windows)
# Download the installer from https://ollama.com/download/windows

# Start the Ollama daemon (runs on http://localhost:11434)
ollama serve

# Pull a vision-capable model
ollama pull llava          # Recommended — best quality (~4 GB)
ollama pull moondream      # Lightweight alternative (~1.7 GB)
ollama pull llava:7b       # Faster, less accurate

# Verify the model is available
ollama list
```

If Ollama is not running or the model is not pulled, the tool **automatically falls back** to an OpenCV-only analysis report with no crash.

---

## Project Files

```
visual_regressor.py      CLI entry point, orchestration, exit codes
image_processor.py       Multi-layer OpenCV analysis engine (SSIM, ORB, Canny, contours)
ai_analyzer.py           Ollama client — replaces all paid LLM dependencies
reporter.py              Console / HTML / JSON report generation
sample_screenshots/      Demo baseline + new deployment screenshots
  baseline.png           Reference HSBC banking dashboard UI
  new_deployment.png     Same UI with deliberate regressions injected
requirements.txt         Python dependencies (opencv, scikit-image, Pillow, requests)
README.md                This file
vrt_output/              Auto-created — stores diff, heatmap, annotated images
```

---

## Example: Detecting a Real Regression

The `sample_screenshots/` directory ships with a before/after pair showing:

- Navigation bar shifted down ~20px
- "Settings" menu item missing
- "Quick Transfer" card removed entirely
- Left sidebar colour changed (dark blue → grey)

Run this to see all regressions detected:

```bash
python visual_regressor.py \
    --baseline sample_screenshots/baseline.png \
    --current  sample_screenshots/new_deployment.png \
    --format html --output report.html --verbose
```

Then open `report.html` in your browser for the full visual comparison.

---

## Requirements

```
opencv-python>=4.8.0      # Image loading, SSIM fallback, edge/contour detection
scikit-image>=0.21.0      # SSIM (primary implementation)
Pillow>=10.0.0            # Image format support
numpy>=1.24.0             # Array operations
requests>=2.31.0          # Ollama HTTP API client
rich>=13.0.0              # Enhanced terminal output
```

Install all with: `pip install -r requirements.txt`

---

## Design Decisions

- **Why SSIM over pixel diff?** SSIM models human perception — small colour shifts score near 1.0 while structural changes (missing elements, layout shifts) correctly score lower.
- **Why ORB feature matching?** Keypoint displacement measures how much structural elements have *moved*, not just *changed*, which is the key signal for layout regressions.
- **Why local Ollama instead of Claude/GPT?** Zero cost, zero data egress, works offline, GDPR-friendly. Any `llava`-compatible model can be swapped in.
- **Why ignore regions?** Timestamps, live price feeds, and animation frames would cause false failures on every run. Masking them before any comparison eliminates an entire class of false positives.
- **Why dilate before contour detection?** Nearby changed pixels that form a single logical element (e.g. a moved button) are merged into one bounding box rather than reported as dozens of separate micro-regions.
