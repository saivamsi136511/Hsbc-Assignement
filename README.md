# HSBC Coding Assignment — AI & Computer Vision Suite

This repository contains five modular, containerized assignments showcasing advanced integration of **Computer Vision (OpenCV)**, **Local Language Models (Ollama / Llama 3.1)**, **Web Scraping/Automation (Selenium)**, and **Resilient Backend Architectures (Flask & SQLite)**.

---

## 🚀 Quick Start with Docker (Recommended)

To run, test, and evaluate all assignments in a clean sandbox container with Chromium and OpenCV graphics dependencies fully pre-configured, use our unified Docker container setup:

### 1. Build the Docker Image
```bash
docker build -t hsbc-assignment .
```

### 2. Run the Interactive Evaluator Tool
```bash
docker run -it -p 5000:5000 hsbc-assignment
```

This starts a console-based selection menu allowing you to launch and validate any of the 5 assignments with one click:
```
================================================================================
                HSBC ASSIGNMENT EVALUATOR MENU
================================================================================
  1) AI-Powered Log Analysis for Root Cause
     Description : Analyzes crash logs under a token budget with dry-run mode.
     Subdirectory: AI-Powered Log Analysis for Root Cause
  2) Automated Test Case Generation
     Description : Runs the test case generator from sample user stories.
     Subdirectory: Automated Test Case Generation
  3) Intelligent Bug Triaging
     Description : Starts the Flask bug triaging web server on port 5000.
     Subdirectory: Intelligent Bug Triaging
  4) Visual Regression Testing with Computer Vision
     Description : Runs the multi-layer OpenCV comparison on dashboard screenshots.
     Subdirectory: Visual Regression Testing with Computer Vision
  5) Self-Healing UI Automation
     Description : Executes Selenium test suite using Ollama to heal broken HTML locators.
     Subdirectory: Self-Healing UI Automation
--------------------------------------------------------------------------------
  q) Quit / Exit
================================================================================
```

---

## 📦 Projects Overview & Verification Commands

If you prefer to run or verify tasks individually, you can use the commands listed below.

| Task | Core Focus | Direct Execution Command |
| :--- | :--- | :--- |
| **1. AI-Powered Log Analysis** | Parse Python/Java/Node/Go crash logs, budget context tokens, redact PII/keys, and query local LLM. | `python "AI-Powered Log Analysis for Root Cause/log_analyzer.py" --dry-run` |
| **2. Automated Test Case Gen** | Ingest User Story specifications, build context templates, and prompt LLM to output structured unit/integration test code. | `python "Automated Test Case Generation/solution.py"` |
| **3. Intelligent Bug Triaging** | Run Flask web server to triaging incoming bugs, detect duplicates, assign team & severity dynamically via SQLite. | `python "Intelligent Bug Triaging/bug_triaging/app.py"` |
| **4. Visual Regression Testing** | Compare BGR screenshots using SSIM, ORB feature shift, and Canny structural edge delta to produce side-by-side HTML heatmaps. | `python "Visual Regression Testing with Computer Vision/visual_regressor.py" --dry-run` |
| **5. Self-Healing Selenium** | Intercept `NoSuchElementException` during browser automation, analyze live DOM structure, and ask local LLM to heal locators. | `python "Self-Healing UI Automation/test_login.py"` |

---

## 🤖 Ollama Setup (For Local AI Operations)

To run the live AI components (Tasks 1, 2, 4, 5) without paid LLM cloud APIs, you need to pull and start a local model using **Ollama**:

### 1. Install & Run Ollama
Download Ollama from [ollama.com](https://ollama.com). Start the service daemon:
```bash
ollama serve
```

### 2. Pull the Required Models
- For text/coding tasks (Tasks 1, 2, 5):
  ```bash
  ollama pull llama3.1
  ```
- For computer vision screenshots (Task 4):
  ```bash
  ollama pull llava
  ```

> [!NOTE]
> All scripts are designed with **robust offline fallbacks**. If Ollama is not running or the model is not found, the scripts will run successfully in **dry-run / CV-only mode** and output clear warning notes rather than crashing.

---

## 📂 Project Structure

```
HSBC Assignment/
├── .gitignore
├── Dockerfile                ← Combined Debian + Chrome + Python wrapper
├── requirements.txt          ← Combined pip dependencies list
├── run.py                    ← Interactive menu entry point
│
├── AI-Powered Log Analysis for Root Cause/
│   ├── log_analyzer.py       ← Log ingest & token budget manager
│   ├── parsers.py            ← Multi-format streaming parser (leaks fixed!)
│   ├── ai_client.py          ← Anthropic API fallback wrapper
│   └── ollama_client.py      ← Standard library Ollama API wrapper
│
├── Automated Test Case Generation/
│   ├── solution.py           ← Story ingestion and testing script
│   └── test_generated.py     ← Generated test suite output
│
├── Intelligent Bug Triaging/
│   ├── app.py            ← Flask server dashboard
│   ├── database.py       ← SQLite schema & data access layer
│   └── triaging_engine.py← Severity, Priority, Assignee engine
│
├── Visual Regression Testing with Computer Vision/
│   ├── visual_regressor.py   ← CLI orchestrator (SSIM, ORB, Canny)
│   ├── image_processor.py    ← Multi-layer OpenCV comparison engine
│   ├── ai_analyzer.py        ← Local Ollama vision analyzer
│   └── reporter.py           ← HTML side-by-side heatmap generator
│
└── Self-Healing UI Automation/
    ├── self_healing_driver.py← Selenium Webdriver finder proxy wrapper
    ├── ollama_healer.py      ← DOM simplifier & locator guesser
    └── test_login.py         ← Login suite with intentionally broken locators
```
