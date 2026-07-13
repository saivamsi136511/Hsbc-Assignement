# AI-Powered Log Analysis for Root Cause

> **Ingest crash logs, pinpoint the offending file and line, and get an actionable fix suggestion — entirely local with Ollama. Supports Python, Java, Node.js, and Go.**

---

## What It Does

Given an application crash log or server log file, this tool:

1. **Parses** structured error records (tracebacks, stack traces) from multiple log formats
2. **Deduplicates** repeated errors (e.g. a retry loop crashing 500 times → 1 finding)
3. **Applies a token budget** to prioritise the most valuable context (error + frames + source code + preceding log lines)
4. **Optionally redacts** secrets (API keys, emails, card numbers) before anything is sent to a model
5. **Calls a local Ollama model** (or Anthropic Claude) to produce structured JSON findings:
   - `summary` — 1–2 sentence plain-English description
   - `likely_file` — path to the offending source file
   - `likely_line` — line number
   - `root_cause` — diagnostic hypothesis
   - `suggested_fix` — concrete investigation step
   - `severity` — critical / high / medium / low
6. **Reports** findings to console, Markdown, or JSON

Works in `--dry-run` mode with no model required — shows what context would have been sent.

---

## Architecture

```
Log File / Stdin
      │
      ▼
┌─────────────────────┐
│   ingestion/        │  ← Multi-format streaming parser
│   parsers.py        │     Python / Java / Node.js / Go / Generic
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   ingestion/        │  ← Fingerprint-based deduplication
│   dedup.py          │     (same error 500 times → 1 finding)
└────────┬────────────┘
         │
         ▼
┌─────────────────────────────────┐
│   context/builder.py            │  ← Token-budgeted context assembly
│   - error type + message        │     Source code lookup (--source-dir)
│   - stack frames                │     PII/secret redaction
│   - preceding log lines         │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│   analysis/                     │  ← LLM backends (pluggable)
│   ollama_client.py              │     OllamaBackend (local, default)
│   anthropic_client.py           │     AnthropicBackend (requires key)
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│   reporting/                    │  ← console / Markdown / JSON
└─────────────────────────────────┘
```

---

## Quick Start

```bash
# 1. Start Ollama
ollama serve
ollama pull llama3.1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Analyse a log (dry-run — no model needed, shows context only)
python log_analyzer.py sample_logs/python_chained.log --dry-run --verbose

# 4. Full AI analysis
python log_analyzer.py sample_logs/python_chained.log

# 5. With source code lookup for better line-level accuracy
python log_analyzer.py crash.log --source-dir /path/to/your/repo

# 6. Output as Markdown report
python log_analyzer.py crash.log --format markdown -o report.md

# 7. Output as JSON (for CI/CD integration)
python log_analyzer.py crash.log --format json -o findings.json

# 8. Use Anthropic Claude instead
python log_analyzer.py crash.log --backend anthropic
```

---

## Supported Log Formats

| Format | Detection Pattern | Example |
|---|---|---|
| **Python** | `Traceback (most recent call last):` | Django, FastAPI, Flask crashes |
| **Java** | `at Class.method(File.java:line)` | Spring Boot, Tomcat |
| **Node.js** | `at Object.<anonymous> (file.js:line)` | Express, Next.js |
| **Go** | `goroutine N [running]:` | Standard library panics |
| **Generic** | `ERROR` / `FATAL` / `PANIC` lines | Any structured text log |

---

## CLI Reference

| Flag | Default | Description |
|---|---|---|
| `log_file` | *(positional)* | Path to log file (use `-` for stdin) |
| `--backend` | `ollama` | AI backend: `ollama` or `anthropic` |
| `--model` | `llama3.1` | Model name |
| `--ollama-url` | `http://localhost:11434` | Ollama server URL |
| `--source-dir` | — | Root of source tree for code-snippet lookup |
| `--format` | `console` | Output format: `console`, `markdown`, `json` |
| `-o / --output` | stdout | Output file path |
| `--token-budget` | `3000` | Max tokens allocated per error context |
| `--max-errors` | `10` | Max distinct errors to analyse per file |
| `--dry-run` | off | Show context without calling the model |
| `--no-redact` | off | Disable PII/secrets redaction |
| `--verbose` | off | Print per-error progress to stderr |

---

## Project Structure

```
AI-Powered Log Analysis for Root Cause/
├── log_analyzer.py          # Main entry point + orchestration + renderers
├── parsers.py               # Multi-format streaming log parser
├── context_builder.py       # Token-budgeted context assembly + redaction
├── analysis_common.py       # AnalysisResult dataclass + shared LLM prompt
├── ollama_client.py         # Free local Ollama backend
├── ai_client.py             # Anthropic Claude backend
├── requirements.txt
│
├── domain/                  # Domain layer (new package structure)
│   ├── models.py            # Re-exports ParsedError, StackFrame, AnalysisResult
│   └── prompts.py           # Shared LLM system prompt + JSON output schema
│
├── ingestion/               # Log ingestion layer
│   ├── parsers.py           # Re-exports streaming parser API
│   └── dedup.py             # Re-exports deduplication helper
│
├── context/                 # Context assembly layer
│   ├── builder.py           # Re-exports build_prompt_context()
│   └── redaction.py         # Re-exports redact()
│
├── analysis/                # AI analysis layer
│   ├── pipeline.py          # Re-exports run(), Finding, collect_errors
│   ├── ollama_client.py     # Re-exports OllamaBackend
│   └── anthropic_client.py  # Re-exports AnthropicBackend
│
├── reporting/               # Report rendering layer
│   ├── console.py           # Re-exports render_console()
│   ├── markdown.py          # Re-exports render_markdown()
│   └── json_report.py       # Re-exports render_json()
│
├── tests/
│   ├── test_parsers.py          # Unit tests for log format parsers
│   ├── test_context_builder.py  # Unit tests for context assembly + redaction
│   └── test_pipeline.py         # Integration tests (no LLM required)
│
└── sample_logs/
    └── python_chained.log   # Demo log with chained exceptions
```

---

## Key Enhancement Features

| Feature | Description |
|---|---|
| **Token budgeting** | Context is assembled in priority order within a configurable token cap — prevents LLM context overflow on large logs |
| **Deduplication** | Fingerprint-based: same error repeated 500× → 1 finding with `occurrence_count=500` |
| **Source code snippets** | With `--source-dir`, the exact source lines around the failing frame are included in the prompt |
| **PII redaction** | API keys, emails, card numbers masked before anything leaves the machine |
| **Streaming dry-run** | `--dry-run` shows exactly what context would have been sent — useful for prompt engineering and token auditing |
| **Pluggable backends** | `OllamaBackend` (local, free) and `AnthropicBackend` (cloud) share the same interface |
| **Package structure** | `ingestion/`, `context/`, `analysis/`, `reporting/` packages for clear separation of concerns |

---

## Sample Output

```
════════════════════════════════════════
 Finding 1 of 2  [CRITICAL]
════════════════════════════════════════
 Error Type  : ConnectionError
 Message     : Stripe API unreachable
 Likely File : /app/gateways/stripe.py
 Likely Line : 15
 Root Cause  : The payment gateway HTTP client failed to connect to Stripe's
               API endpoint. Likely a network partition or DNS failure.
 Suggested Fix: Check network connectivity from the app server to
               api.stripe.com. Verify DNS resolution and firewall rules.
               Consider adding a circuit breaker for the Stripe client.
 Confidence  : high
════════════════════════════════════════
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| No errors detected in log | Log format may be generic — try `--verbose` to see parsing progress |
| `likely_file: null` | Add `--source-dir` to enable frame-to-source resolution |
| Model times out | Use `--token-budget 1000` to reduce context; or use `llama3.2:3b` |
| PII in report | Run with `--no-redact` disabled (default is to redact) |

---

## Execution Evidence
<details>
<summary><b>Click to view Log Analysis Screenshots</b></summary>

1. **Unit Test Execution (`pytest tests/ -v`)**
   ![Log Analysis Tests](../assets/screenshots/11_loganalysis_pytest.png)

2. **Dry Run Mode (Log Ingestion, Redaction & Context assembly)**
   ![Log Analysis Dry Run](../assets/screenshots/12_loganalysis_dryrun.png)

3. **Full AI Analysis (Identified Root Cause & Suggestion)**
   ![Log Analysis Full Run](../assets/screenshots/13_loganalysis_full_run.png)

4. **Generated Markdown Report opened in Editor**
   ![Log Analysis Report](../assets/screenshots/14_loganalysis_markdown_report.png)
</details>
