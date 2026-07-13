# Visual Regression Testing with Computer Vision

> **AI-powered screenshot comparison using OpenCV + local Ollama vision models. Detects layout shifts, colour changes, missing elements — zero cloud, zero cost.**

---

## What It Does

Given a baseline screenshot and a current (post-deployment) screenshot, this tool:

1. **Computes SSIM** (Structural Similarity Index) — an overall perceptual quality score
2. **Detects layout shifts** using ORB feature matching — identifies elements that moved ≥20 px
3. **Detects structural changes** via Canny edge-map comparison — elements added or removed
4. **Groups changed pixels** into bounding-box regions with per-region severity scores
5. **Detects colour/theme regressions** via per-channel histogram correlation
6. **Calls a vision model** (Ollama `llava`, `moondream`) to produce a plain-English report of what changed and why it matters
7. **Saves annotated output images** (diff, heatmap, bounding boxes) to an output directory
8. **Supports dynamic content masking** (`--ignore-region`) for timestamps, ads, live feeds

Works in `--dry-run` mode with zero model calls — OpenCV metrics only.

---

## Architecture

```
Baseline Screenshot          Current Screenshot
        │                           │
        └───────────┬───────────────┘
                    ▼
        ┌───────────────────────┐
        │   vrt/processor.py   │  ← 5-layer OpenCV comparison engine
        │   ImageProcessor     │
        │   ─ SSIM             │  Overall perceptual similarity
        │   ─ ORB features     │  Layout shift detection (>20px)
        │   ─ Canny edges      │  Structural element add/remove
        │   ─ Contour regions  │  Bounding boxes of changed areas
        │   ─ Histograms       │  Colour/theme/stylesheet changes
        └────────┬──────────────┘
                 │
                 ▼
        ┌───────────────────────┐
        │   vrt/ai.py           │  ← Local Ollama vision model
        │   OllamaAnalyzer      │     (llava, moondream, llava:7b)
        │   (dry-run = skipped) │
        └────────┬──────────────┘
                 │
                 ▼
        ┌───────────────────────┐
        │   vrt/reporter.py     │  ← console / HTML / JSON output
        └───────────────────────┘
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Dry-run (OpenCV metrics only, no model needed)
python visual_regressor.py \
  --baseline sample_screenshots/baseline.png \
  --current  sample_screenshots/new_deployment.png \
  --dry-run  --verbose

# 3. Full AI analysis with Ollama vision model
ollama serve
ollama pull llava
python visual_regressor.py \
  --baseline sample_screenshots/baseline.png \
  --current  sample_screenshots/new_deployment.png \
  --model llava

# 4. Generate an HTML report
python visual_regressor.py \
  --baseline baseline.png --current current.png \
  --format html -o report.html

# 5. JSON output for CI/CD
python visual_regressor.py \
  --baseline baseline.png --current current.png \
  --format json -o results.json

# 6. Mask a dynamic region (e.g. a live timestamp at top-right)
python visual_regressor.py \
  --baseline baseline.png --current current.png \
  --ignore-region 900,0,300,40

# 7. Fail the CI build if SSIM < 0.97
python visual_regressor.py \
  --baseline baseline.png --current current.png \
  --threshold 0.97
echo "Exit code: $?"   # 0 = passed, 1 = regression detected
```

---

## Comparison Layers

| Layer | Metric | What It Catches |
|---|---|---|
| **SSIM** | 0.0–1.0 (higher = better) | Overall visual change; primary pass/fail signal |
| **ORB Features** | Average keypoint displacement (px) | Elements shifted by layout changes (CSS, flexbox, grid) |
| **Canny Edges** | % differing edge pixels | Structural elements added or removed (buttons, panels, modals) |
| **Contour Regions** | Bounding boxes + severity | Locates exactly where changes occurred on the page |
| **Histograms** | Per-channel correlation (0–1) | Colour theme changes, dark-mode regression, palette swaps |

---

## CLI Reference

| Flag | Default | Description |
|---|---|---|
| `--baseline` | *(required)* | Baseline screenshot path |
| `--current` | *(required)* | Current screenshot path |
| `--threshold` | `0.95` | SSIM threshold; below this = regression |
| `--model` | `llava` | Ollama vision model |
| `--ollama-url` | `http://localhost:11434` | Ollama server URL |
| `--format` | `console` | Output format: `console`, `html`, `json` |
| `-o / --output` | stdout | Output file path |
| `--output-dir` | `vrt_output` | Directory for saved diff/heatmap/annotated images |
| `--ignore-region` | — | Repeatable: `X,Y,W,H` regions to mask (e.g. timestamps) |
| `--dry-run` | off | Run OpenCV only, skip Ollama model |
| `--save-images` | off | Save diff, heatmap, annotated images to `--output-dir` |
| `--verbose` | off | Print per-layer progress to stderr |

---

## Project Structure

```
Visual Regression Testing with Computer Vision/
├── visual_regressor.py      # CLI entry point + orchestration
├── image_processor.py       # 5-layer OpenCV comparison engine
├── ai_analyzer.py           # Ollama vision model client
├── reporter.py              # console / HTML / JSON renderers
├── requirements.txt
├── README.md
│
├── vrt/                     # New package structure
│   ├── __init__.py
│   ├── constants.py         # ALL thresholds, defaults, paths
│   ├── models.py            # ComparisonResult, AIAnalysisResult re-exports
│   ├── utils.py             # log() helper + parse_ignore_regions()
│   ├── cli.py               # parse_args() / main() adapter
│   ├── processor.py         # ImageProcessor adapter
│   ├── ai.py                # OllamaAnalyzer adapter
│   └── reporter.py          # Reporter adapter
│
├── tests/
│   ├── test_processor.py    # SSIM + error-handling tests (no GPU needed)
│   ├── test_ai.py           # AI client tests (Ollama mocked)
│   ├── test_reporter.py     # Report rendering tests
│   └── test_cli.py          # Argument parsing tests
│
└── sample_screenshots/
    ├── baseline.png         # Pre-deployment bank dashboard screenshot
    └── new_deployment.png   # Post-deployment screenshot (with intentional regressions)
```

---

## Key Enhancement Features

| Feature | Description |
|---|---|
| **5-layer comparison** | SSIM + ORB + Edges + Contours + Histograms — each catches different failure modes |
| **False-positive reduction** | Ignore regions + Gaussian blur + minimum area filtering remove noise |
| **Local vision model** | `llava` via Ollama — detailed AI analysis with zero data egress |
| **Graceful dry-run** | `--dry-run` skips the model; pure OpenCV metrics for offline CI runs |
| **Exit code integration** | Returns exit code 1 on regression — works natively in CI pipelines |
| **`vrt/constants.py`** | All SSIM thresholds, ORB params, Canny values in one file |
| **`vrt/utils.py`** | `parse_ignore_regions()` helper for masking dynamic content zones |
| **CI/CD ready** | JSON format + exit codes + configurable thresholds |

---

## Ollama Vision Models

| Model | Size | Notes |
|---|---|---|
| `llava` | ~4 GB | Recommended — strong visual reasoning |
| `llava:7b` | ~4.5 GB | More detailed descriptions |
| `moondream` | ~1.7 GB | Fastest — good for CI environments |

---

## CI/CD Integration Example (GitHub Actions)

```yaml
- name: Visual Regression Test
  run: |
    python visual_regressor.py \
      --baseline screenshots/baseline.png \
      --current screenshots/current.png \
      --threshold 0.95 --format json \
      -o vrt_results.json --dry-run
  # Exit code 1 = regression detected → build fails automatically
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| False positives on timestamps | Add `--ignore-region X,Y,W,H` for the clock/date area |
| SSIM too strict | Lower `--threshold` to `0.90` |
| Model too slow | Use `moondream` (~1.7 GB) instead of `llava` |
| OpenCV not found | Run `pip install opencv-python-headless scikit-image` |

---

## Execution Evidence
<details>
<summary><b>Click to view Visual Regression Screenshots</b></summary>

1. **Unit Test Execution (`pytest tests/ -v`)**
   ![VRT Tests](../assets/screenshots/15_vrt_pytest.png)

2. **UI Mock Verification (New deployment layout opened in editor)**
   ![VRT Screenshot Input](../assets/screenshots/16_vrt_new_deployment.png)

3. **Visual Regression Run (OpenCV structural metric assessment & semantic LLM check)**
   ![VRT Execution Run](../assets/screenshots/17_vrt_run.png)
</details>
