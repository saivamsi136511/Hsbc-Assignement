# AI-Powered Log Analysis for Root Cause

Ingests application crash logs / stack traces and asks Claude to produce, per
distinct error: a plain-English summary, the likely offending file/line, a
root-cause hypothesis, and a suggested fix or workaround.

# AI-Powered Log Analysis for Root Cause

Ingests application crash logs / stack traces and asks an LLM to produce,
per distinct error: a plain-English summary, the likely offending
file/line, a root-cause hypothesis, and a suggested fix or workaround.

Runs against **free, local Ollama by default** — no API key, no
per-token cost, nothing leaves your machine. The Claude API is also
supported as an optional higher-quality backend.

## Quick start (Ollama — free, local, default)

```bash
# 1. Install Ollama: https://ollama.com/download
# 2. Start the server (leave this running in a terminal)
ollama serve

# 3. Pull a model (one-time). A coding-tuned model does noticeably better
#    at this task than a general chat model:
ollama pull qwen2.5-coder        # good balance of speed/quality, ~4.7GB
# or: ollama pull llama3.1       # general-purpose, this tool's default
# or: ollama pull deepseek-coder-v2   # stronger, needs more RAM

# 4. No pip install needed for this path — ollama_client.py uses only the
#    Python standard library. Just run it:
python log_analyzer.py sample_logs/python_crash.log --model qwen2.5-coder

# Or use the default model (llama3.1) with no --model flag:
python log_analyzer.py sample_logs/python_crash.log
```

If `ollama serve` isn't running, or the model isn't pulled yet, the tool
tells you exactly what to do rather than a raw connection error:

```
error: Couldn't reach Ollama at http://localhost:11434 (Connection refused).
Is it running? Start it with `ollama serve`.
```

## Quick start (Claude API — optional, higher quality)

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python log_analyzer.py sample_logs/python_crash.log --backend anthropic
```

## Other useful flags (either backend)

```bash
# Point at your source checkout so the AI gets real code context, not just the trace
python log_analyzer.py sample_logs/python_crash.log --source-dir /path/to/your/repo

# Pipe logs in directly (e.g. from a running service)
tail -n 500 /var/log/app.log | python log_analyzer.py -

# See exactly what would be sent to the model, with zero calls/cost
python log_analyzer.py sample_logs/python_crash.log --dry-run

# Write a shareable markdown report instead of printing to console
python log_analyzer.py sample_logs/java_crash.log -o report.md --format markdown

# Point at a remote/custom Ollama host
python log_analyzer.py crash.log --ollama-host http://192.168.1.50:11434
```

Try it against the bundled samples in `sample_logs/` — `python_crash.log`,
`java_crash.log`, `node_crash.log`, `go_panic.log`, `deep_recursion.log`
(stack-overflow-scale trace), and `unrecognized_format.log` (a made-up
custom logger format, to see the generic fallback in action). `--dry-run`
works on all of them with no server or API key needed at all.

## What it actually does

1. **Parse** — streams the log and extracts structured errors: type,
   message, stack frames, timestamp, and the log lines immediately
   preceding the crash. Supports Python, Java, Node/JavaScript, and Go
   panics natively; anything else falls back to a generic detector that
   groups contiguous `ERROR`/`FATAL`/`PANIC`-flagged lines.
2. **Deduplicate** — the same crash repeated 500 times in a log (extremely
   common) collapses into one entry with an occurrence count, so you're not
   paying to analyze the same bug 500 times.
3. **Build context under a token budget** — for each *distinct* error,
   assembles a prioritized payload: error message (always) → stack trace,
   capped and truncated for pathological cases like deep recursion (always)
   → real source code around the likely offending frame, if `--source-dir`
   is given and the file is found locally (best-effort) → preceding log
   lines, filling whatever budget remains.
4. **Analyze** — sends that context to the configured backend (Ollama by
   default, or Claude via `--backend anthropic`) with a system prompt that
   requires structured JSON output (summary, likely file/line, root cause,
   confidence, suggested fix, workaround, severity), so results are
   consistent and easy to consume programmatically regardless of backend.
5. **Report** — console, Markdown, or JSON.

## Design decisions worth knowing about

- **Backends are pluggable and share one output schema.** `analysis_common.py`
  holds the result dataclass, the system prompt, and defensive JSON parsing;
  both `ollama_client.py` and `ai_client.py` just call a model and hand the
  text back to it. Report rendering never needs to know which backend ran.
  Ollama's response quality varies more than Claude's with model choice and
  size — a coding-tuned local model (`qwen2.5-coder`, `deepseek-coder-v2`)
  will follow the "JSON only" instruction and reason about code more
  reliably than a small general chat model.
- **Token budgeting is a heuristic (`chars / 4`)**, not an exact count. It's
  good enough for the truncation/prioritization decisions this tool makes.
  For exact pre-flight counts, swap in the Anthropic API's
  `client.messages.count_tokens()`.
- **"Likely offending frame" isn't just the top of the stack.** The top
  frame is frequently inside a library or framework, not the app's actual
  bug. Frames are ranked by a simple own-code heuristic (skips
  `site-packages`, `node_modules`, JVM/stdlib packages, etc.) so source
  lookup and the "likely file" hint point at application code first.
- **Secrets are redacted before anything is sent to the API**, by default:
  API keys, bearer tokens, emails, and card-number-shaped strings are
  stripped from both the AI-bound context *and* the on-screen report.
  Disable with `--no-redact` if you're sure your logs are already clean and
  want to see the exact original text.
- **Massive stack traces (deep recursion, stack overflow) are truncated to
  head + tail** with an explicit "N frames omitted" marker rather than
  either silently dropping context or blowing the token budget on hundreds
  of near-identical frames.
- **The tool is honest about degraded context.** When source files aren't
  found, frames get truncated, or preceding log context gets cut for
  budget, that shows up as a `note:` in the report — the AI's confidence
  field is also expected to reflect this ("high" confidence should mean the
  evidence actually supports it).
- **JSON parsing from the model is defensive**: strips markdown code fences,
  falls back to extracting the first `{...}` blob if the model adds stray
  prose despite instructions, and surfaces a clear error rather than
  crashing if the response still isn't parseable.
- **Transient API failures retry with exponential backoff** (2 retries by
  default); a hard failure is reported per-error rather than aborting the
  whole run, so one bad call doesn't lose analysis of everything else.

## CLI reference

```
python log_analyzer.py INPUT [options]

INPUT                     Path to a log file, or '-' for stdin

--source-dir DIR          Your source checkout, for real code context
-o, --output FILE         Write report to a file instead of stdout
--format {console,markdown,json}   Output format (default: console)
--backend {ollama,anthropic}       Which LLM backend to use (default: ollama, free/local)
--model MODEL             Model name (default: llama3.1 for ollama, claude-sonnet-4-6 for anthropic)
--ollama-host URL         Ollama server URL (default: http://localhost:11434, or $OLLAMA_HOST)
--api-key KEY             Anthropic API key, only used with --backend anthropic
--max-context-tokens N    Token budget per error sent to the model (default: 4000)
--context-lines N         Source lines shown above/below the offending line (default: 6)
--max-errors N            Cap on distinct errors analyzed after dedup (default: 10)
--dry-run                 Parse + build context only, no model calls, no cost
--no-redact               Disable secret redaction (off by default means redaction is ON)
--verbose, -v             Progress output to stderr
```

## Known limitations

- Format detection is regex-based. Highly unusual or heavily customized log
  formats will land in the generic fallback, which still gets grouped and
  sent to the AI, but without structured frame data (so "likely file/line"
  relies entirely on what the model can infer from raw text).
- If a log file mixes multiple *structured* formats (e.g. a Java service
  that shells out to a Python script, both logging to the same file), the
  streaming parser recognizes each error independently as it scans, so this
  works — but a log with zero recognized structured errors falls back to
  the generic detector for the *entire* file rather than a per-line mix.
- Source lookup is best-effort path matching (tries the path as logged,
  then relative to `--source-dir`). Deployment paths that differ
  significantly from your local checkout (e.g. Docker `/app/...` vs. a
  differently laid-out repo) may not resolve — this shows up as a `note:`
  in the report rather than failing silently.
- This tool sends log content (redacted, by default) to the Anthropic API.
  Review `--dry-run` output before running for real if your logs might
  contain data your redaction rules don't catch.

## Files

```
log_analyzer.py        CLI entry point, orchestration, report rendering
parsers.py              Log parsing: Python / Java / Node / Go / generic, dedup
context_builder.py      Token budgeting, source snippet lookup, redaction
analysis_common.py      Shared result schema, prompt, JSON parsing (both backends)
ollama_client.py        Ollama backend (free, local, default) -- stdlib only
ai_client.py             Claude API backend (--backend anthropic)
sample_logs/            Example crash logs for every supported format
sample_source/          Toy source tree matching python_crash.log's paths,
                        so --source-dir code-context lookup can be demoed
requirements.txt        Only needed for --backend anthropic
```
