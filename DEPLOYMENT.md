# Deployment Guide — HSBC AI for QA Tooling Suite

> **Step-by-step setup from zero to running all five modules locally.**

---

## System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| **OS** | Windows 10 / macOS 12 / Ubuntu 22.04 | Ubuntu 22.04 LTS |
| **Python** | 3.10 | 3.11+ |
| **RAM** | 8 GB | 16 GB (for Ollama + llama3.1) |
| **Disk** | 10 GB free | 20 GB free |
| **CPU** | x86-64 | x86-64 with AVX2 (faster inference) |
| **GPU** | Optional | NVIDIA with CUDA 12+ (significantly faster) |

---

## Step 1 — Install Python 3.10+

```bash
# Verify Python is installed
python --version
# Expected: Python 3.10.x or higher

# If not installed:
# Windows:  https://www.python.org/downloads/
# macOS:    brew install python@3.11
# Ubuntu:   sudo apt install python3.11 python3.11-venv
```

---

## Step 2 — Install Ollama (Local LLM Runtime)

```bash
# Download from: https://ollama.com/download
# Or via script (macOS/Linux):
curl -fsSL https://ollama.com/install.sh | sh

# Windows: Download the .msi installer from https://ollama.com/download
```

### Start the Ollama Server

```bash
# Keep this terminal open (or run as a background service)
ollama serve
```

### Pull Required Models

```bash
# Primary model — used by Modules 1, 2, 3, 5
ollama pull llama3.1

# Vision model — required for Module 4 (Visual Regression) semantic analysis
ollama pull llava
```

> **Note:** `llama3.1` is ~4.7 GB. `llava` is ~4.5 GB. Allow 10–15 minutes on a typical connection.

### Verify Ollama is Running

```bash
curl http://localhost:11434/api/tags
# Should return a JSON list of available models
```

---

## Step 3 — Clone / Extract the Repository

```bash
# If using Git:
git clone <repository-url> "HSBC Assignment"
cd "HSBC Assignment"

# If using a ZIP archive:
unzip HSBC_Assignment.zip
cd "HSBC Assignment"
```

---

## Step 4 — Create a Virtual Environment (Recommended)

```bash
python -m venv .venv

# Activate (Windows PowerShell):
.venv\Scripts\Activate.ps1

# Activate (Windows CMD):
.venv\Scripts\activate.bat

# Activate (macOS/Linux):
source .venv/bin/activate
```

---

## Step 5 — Install Python Dependencies

```bash
# Install all dependencies from the root requirements file
pip install -r requirements.txt

# Verify key packages installed correctly
python -c "import cv2, flask, selenium; print('All packages OK')"
```

> **Pydantic note:** Module 2 (Bug Triaging) uses Pydantic v2.x. If you see a
> `ValidationError` import error, run: `pip install "pydantic>=2.0"`

---

## Step 6 — Module-Specific Setup

### Module 1 — Automated Test Case Generation

```bash
cd "Automated Test Case Generation"
# Dry-run demo (no Ollama needed)
python generate_tests.py -i samples/sample_user_story.md --dry-run
# Full AI generation
python generate_tests.py -i samples/sample_user_story.md
```

### Module 2 — AI-Powered Log Analysis

```bash
cd "AI-Powered Log Analysis for Root Cause"
# Dry-run demo (no Ollama needed)
python log_analyzer.py sample_logs/python_chained.log --dry-run --verbose
# Full AI analysis
python log_analyzer.py sample_logs/python_chained.log
# Output as Markdown report
python log_analyzer.py sample_logs/python_chained.log --format markdown -o report.md
```

### Module 3 — Intelligent Bug Triaging (Flask + SQLite)

The SQLite database (`bugs.db`) is created automatically on first run.

```bash
cd "Intelligent Bug Triaging"
# No Ollama needed — heuristics-only mode
python app.py --provider none
# Full AI triage mode
python app.py
# Visit the dashboard at: http://localhost:5000
```

### Module 4 — Visual Regression Testing (OpenCV + Vision Model)

The `llava` vision model (pulled in Step 2) is required for semantic analysis.
OpenCV-only comparison works without Ollama using `--dry-run`.

```bash
cd "Visual Regression Testing with Computer Vision"
# Dry-run (OpenCV only, no vision model)
python visual_regressor.py \
  --baseline sample_screenshots/baseline.png \
  --current  sample_screenshots/new_deployment.png \
  --dry-run --verbose
# Full analysis with vision model
python visual_regressor.py \
  --baseline sample_screenshots/baseline.png \
  --current  sample_screenshots/new_deployment.png
```

### Module 5 — Self-Healing UI Automation (Selenium)

Requires Google Chrome to be installed. `webdriver-manager` automatically downloads the matching ChromeDriver.

```bash
# Verify Chrome is installed:
# Windows: "C:\Program Files\Google\Chrome\Application\chrome.exe" --version
# Linux:   google-chrome --version
# macOS:   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --version

cd "Self-Healing UI Automation"
# Ensure Ollama is running with llama3.1 pulled first
python test_login.py
```

---

## Step 7 — Launch the Interactive Menu

```bash
# From the root HSBC Assignment/ directory:
python run.py
```

Select a module number (1–5) and press Enter. The menu also accepts direct
arguments: `python run.py 3` launches Module 3 immediately.

---

## Running Without Ollama — Demonstration Mode

Every module supports demo operation without an LLM:

| Module | Demo Command |
|---|---|
| Test Generation | `python generate_tests.py -i samples/sample_user_story.md --dry-run` |
| Log Analysis | `python log_analyzer.py sample_logs/python_chained.log --dry-run` |
| Bug Triaging | `python app.py --provider none` |
| Visual Regression | `python visual_regressor.py --baseline ... --current ... --dry-run` |
| Self-Healing | *(requires Ollama — browser automation is inherently live)* |

---

## Running the Full Test Suite

```bash
# From the root directory — discovers all tests across all modules
pytest --tb=short -q

# Per-module test runs:
pytest "Automated Test Case Generation/tests/"    -v
pytest "Intelligent Bug Triaging/tests/"           -v
pytest "AI-Powered Log Analysis for Root Cause/tests/" -v
pytest "Visual Regression Testing with Computer Vision/tests/" -v
```

Expected: **13 test files**, all passing.

---

## Docker Deployment (Optional)

A `Dockerfile` is provided at the repository root for containerised evaluation.

```bash
# Build the image
docker build -t hsbc-qa-suite .

# Run the interactive menu
docker run -it --rm -p 5000:5000 hsbc-qa-suite

# Run only the Bug Triaging dashboard
docker run -it --rm -p 5000:5000 hsbc-qa-suite \
  python "Intelligent Bug Triaging/app.py" --provider none
```

> **Ollama with Docker:** The container expects Ollama running on the host.
> Pass the host URL via environment variable:
> ```bash
> docker run -it --rm -p 5000:5000 \
>   -e OLLAMA_BASE_URL="http://host.docker.internal:11434" \
>   hsbc-qa-suite
> ```

---

## Optional — Anthropic Claude API (Cloud Alternative)

Modules 1, 2, and 3 support Anthropic Claude as an alternative to local Ollama.

```bash
# Set your API key (never commit this to source control)
export ANTHROPIC_API_KEY="sk-ant-..."   # macOS/Linux
$env:ANTHROPIC_API_KEY="sk-ant-..."    # Windows PowerShell

# Module 2 — Log Analysis with Claude
cd "AI-Powered Log Analysis for Root Cause"
python log_analyzer.py sample_logs/python_chained.log --backend anthropic

# Module 3 — Bug Triaging with Claude
cd "Intelligent Bug Triaging"
python app.py --provider anthropic
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `ollama: command not found` | Ollama not installed or not in PATH | Reinstall from https://ollama.com/download |
| `ConnectionRefusedError` at port 11434 | Ollama server not running | Run `ollama serve` in a separate terminal |
| `ModuleNotFoundError: cv2` | OpenCV not installed | `pip install opencv-python-headless` |
| `ModuleNotFoundError: skimage` | scikit-image missing | `pip install scikit-image` |
| `SessionNotCreatedException` (Selenium) | Chrome/ChromeDriver version mismatch | `pip install --upgrade webdriver-manager` |
| Flask port 5000 in use | Another process using the port | Kill the other process, or edit `app.py` to use a different port |
| `RuntimeError: CUDA out of memory` | GPU VRAM insufficient for llama3.1 | Use a smaller model: `ollama pull llama3.2:3b` |
| Model responses very slow (CPU) | No GPU acceleration | Set `OLLAMA_NUM_GPU=1` or use `llama3.2:3b` |
| `pydantic.errors.PydanticImportError` | Pydantic v1 installed | `pip install "pydantic>=2.0"` |
| `sqlalchemy` import error in Bug Triaging | Missing dependency | `pip install -r "Intelligent Bug Triaging/requirements.txt"` |

---

## Verified Working Configuration

| Component | Version |
|---|---|
| Python | 3.11.9 |
| Ollama | 0.3.x |
| Model: llama3.1 | 8B Q4_K_M |
| Model: llava | 7B Q4_K_M |
| OpenCV (headless) | 4.9.0 |
| Flask | 3.0.x |
| Selenium | 4.20.x |
| Pytest | 8.1.x |
| Pydantic | 2.6.x |
