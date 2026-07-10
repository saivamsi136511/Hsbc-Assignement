# AI-Powered Log Analysis for Root Cause

A single-file Python script that ingests application crash logs / stack
traces and produces:

- a **plain-English summary** of what went wrong
- the **likely offending file/line/function**
- a **suggested fix** and a **short-term workaround**

It uses a **free, local LLM via [Ollama](https://ollama.com)** by default, and
falls back to a **deterministic, fully offline heuristic analyzer** when no
LLM is reachable — so the tool never leaves you with nothing.

---

## 1. Quick start

```bash
# One-time setup (see https://ollama.com for install instructions)
ollama serve &
ollama pull llama3.1          # or a coding-tuned model, see "Model choice" below

# Analyze a crash log
python3 log_analyzer.py crash.log

# Pipe logs in directly
kubectl logs my-pod | python3 log_analyzer.py -

# No Ollama installed / no GPU / just want it to work offline right now:
python3 log_analyzer.py crash.log --provider none
```

No third-party Python packages are required — it only uses the standard
library, so there's nothing to `pip install`.

---

## 2. What it actually does

1. **Ingests** a file, a directory of `*.log`/`*.txt` files, or stdin.
2. **Detects the log format** (Python, Java, Node.js/JavaScript, Go, C#/.NET,
   or a generic fallback) and **parses out structured stack frames** —
   file, line, function — plus the exception type/message, including
   **chained/nested exceptions** (Python's "During handling of...", Java's
   "Caused by:", .NET's inner exceptions).
3. **Builds a compact, information-dense context** for the LLM instead of
   dumping the raw log — this is the "context window management" piece:
   it labels which exception in a chain is the root cause vs. the symptom,
   collapses repeated frames (e.g. deep recursion), and shrinks gracefully
   if the evidence would still be too large for the model's context window.
4. **Redacts likely secrets** (API keys, bearer/JWT tokens, emails, IPs)
   before anything is sent to an LLM. On by default.
5. **Asks the LLM** (Ollama by default) for a structured JSON report:
   summary, root cause, offending location, suggested fix, workaround,
   category, severity, confidence.
6. **Cross-checks the model's answer against the evidence** it was actually
   given — if the model names a file/line that was never extracted from the
   log, the report is flagged `[UNVERIFIED — hypothesis]` instead of being
   presented as fact.
7. **Falls back to a heuristic, rule-based report** (no LLM at all) if
   Ollama isn't running, isn't reachable, or you pass `--provider none` —
   so the tool is useful even fully offline.

---

## 3. Usage

```
python3 log_analyzer.py INPUT [options]

INPUT                 A log file path, a directory of *.log/*.txt files, or '-' for stdin

--provider {ollama,openai,none}   LLM backend (default: ollama)
--model MODEL                     Model name (default: llama3.1)
--ollama-url URL                  Ollama base URL (default: http://localhost:11434)
--api-base URL                    Base URL for --provider openai (any OpenAI-compatible server)
--api-key KEY                     API key for --provider openai (or set OPENAI_API_KEY)
--timeout N                       LLM request timeout in seconds (default: 60)
--strict-llm                      Error out instead of silently falling back to heuristics
--max-context-chars N             Max evidence chars sent to the LLM per event (default: 6000)
--max-read-bytes N                Tail-read cap for huge files (default: 2,000,000)
--which {last,first,all}          Which crash event(s) to analyze if there are several (default: last)
--output {text,json,markdown}     Report format (default: text)
--save PATH                       Also write the report to this file
--no-redact                       Disable automatic secret/PII redaction (on by default)
--verbose                         Extra diagnostics on stderr
```

### Examples

```bash
# Use a coding-tuned local model for better line-level precision
python3 log_analyzer.py crash.log --model qwen2.5-coder:7b

# Batch-analyze a whole directory of logs, save Markdown reports
python3 log_analyzer.py ./var/logs --output markdown --save report.md

# A log with several unrelated crashes: analyze every one of them
python3 log_analyzer.py app.log --which all

# Talk to any OpenAI-compatible local server (LM Studio, vLLM, etc.) instead of Ollama
python3 log_analyzer.py crash.log --provider openai --api-base http://localhost:1234/v1 --model local-model

# Fully offline, no LLM at all
python3 log_analyzer.py crash.log --provider none
```

### Model choice

`llama3.1` is a reasonable general-purpose default. For sharper file/line
and fix suggestions, a **code-tuned** model tends to do noticeably better,
e.g. `ollama pull qwen2.5-coder:7b` or `ollama pull deepseek-coder-v2`, then
pass `--model qwen2.5-coder:7b`.

---

## 4. Architecture (why it's built this way)

- **Language-aware frame ordering.** This is the easiest thing to get wrong
  and it directly determines whether the tool points at the right line.
  Python's traceback docs literally say *"most recent call last"* — the
  **last** `File "...", line N` entry is where the exception actually fired.
  Java, Node.js, Go, and C# do the **opposite**: the **first** `at ...` line
  is the actual failure point. The script normalizes this (`actual_frame()`,
  `normalize_frames_most_specific_first()`) so both the heuristic analyzer
  and the LLM prompt always see "most specific frame first," regardless of
  source language.
- **Root cause vs. symptom in chained exceptions** is also
  language-dependent: in Java/.NET, the *last* "Caused by"/inner exception
  is the deepest/original cause. In Python, it's the *opposite* — the
  *first* traceback is the original exception, and anything after "During
  handling of..." is a later re-raise that wraps it. Both are handled
  explicitly (see `parse_python` vs `parse_java`/`parse_csharp`), and
  `CrashEvent.root_cause` looks up by semantic role, not list position.
- **Verification, not trust.** LLMs — especially small local ones — will
  occasionally invent a plausible-looking file/line. Every report is
  cross-checked against the frames actually extracted from the log; unverified
  claims are labeled as hypotheses, not facts.

---

## 5. Edge cases this handles

| Scenario | Behavior |
|---|---|
| Ollama not running / unreachable | Warns on stderr, falls back to the heuristic analyzer (or errors cleanly with `--strict-llm`) |
| Model not pulled | Detects Ollama's 404 and tells you exactly what to run (`ollama pull <model>`) |
| LLM returns malformed/wrapped JSON | Recovers from markdown fences or stray prose; last resort shows raw text instead of crashing |
| LLM hallucinates a file/line | Flagged `[UNVERIFIED — hypothesis]` after cross-checking against extracted frames |
| Empty / whitespace-only input | Skipped with a clear warning, not a crash |
| Binary / non-UTF-8 / garbled input | Multi-encoding decode attempt, then graceful "nothing to analyze" instead of a crash |
| Huge log files (100MB+) | Tail-read cap (`--max-read-bytes`, default 2MB) — crashes are almost always near the end |
| Log context too large for the model | Progressive shrinking (fewer frames per exception) rather than an abrupt mid-word cutoff |
| Deep recursion / stack overflow (100s of identical frames) | Repeated frame runs collapse to one annotated entry (`[repeated 42x]`) |
| Multiple unrelated crashes in one log | `--which {last,first,all}` controls which crash event(s) get analyzed |
| Chained/nested exceptions | Full chain is parsed and passed to the LLM with explicit root-cause/symptom labels |
| Secrets/PII in logs (API keys, JWTs, emails, IPs) | Redacted by default before anything is sent to an LLM (`--no-redact` to disable) |
| ANSI color codes from terminal-captured logs | Stripped before parsing |
| Unrecognized/unknown log format | Generic severity-line fallback parser (`ERROR`/`FATAL`/`Exception`/`panic`) instead of failing |
| Directory of many log files | Batch mode: globs `*.log`/`*.txt` and reports on each |
| Network/timeout talking to the LLM | Retries with backoff, then a clear error or fallback |

### Known limitations (documented, not silently papered over)
- Splitting a log into separate "crash events" uses per-language start
  markers (`Traceback (most recent call last):`, `Exception in thread`,
  `panic:`, etc.); pathological interleavings of multiple threads' logs
  can still confuse the boundary detection.
- Non-English exception messages are passed through as-is; results depend
  on the chosen model's multilingual ability.
- This is heuristic + LLM assistance, not a guarantee — always sanity-check
  a suggested fix against the actual codebase before applying it, especially
  anything marked `[UNVERIFIED]` or `confidence: low`.

---

## 6. Files in this project

```
log_analyzer.py          The script (parsing, context management, LLM client, CLI)
test_log_analyzer.py     Offline unit tests (no LLM/network needed) — run: python3 test_log_analyzer.py
sample_logs/             Example crash logs (Python, Java, Node, Go, generic, secrets+recursion) for testing
README.md                This file
```
