"""
ollama_client.py
=================
Ollama backend: free, local, offline analysis via a locally running Ollama
server (https://ollama.com). No API key, no per-token cost, nothing leaves
your machine.

Setup (one-time):
    1. Install Ollama: https://ollama.com/download
    2. Start the server:      ollama serve
    3. Pull a model:          ollama pull llama3.1
       (a coding-tuned model tends to do better on this task, e.g.
        `ollama pull qwen2.5-coder` or `ollama pull deepseek-coder-v2`)

Then run this tool with --backend ollama (the default) and --model set to
whatever you pulled (default: llama3.1).

Uses only the Python standard library (urllib) so there's no extra pip
dependency for the free path -- `anthropic` is only needed if you use
--backend anthropic.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Optional

from analysis_common import AnalysisResult, SYSTEM_PROMPT, parse_json_response

DEFAULT_MODEL = "llama3.1"
DEFAULT_HOST = "http://localhost:11434"


class OllamaBackend:
    name = "ollama"

    def __init__(self, model: str = DEFAULT_MODEL, host: Optional[str] = None,
                 max_retries: int = 1, request_timeout: float = 180.0):
        self.model = model
        self.host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")
        self.max_retries = max_retries
        # Local models on CPU can be slow; default timeout is generous on purpose.
        self.request_timeout = request_timeout

    def analyze(self, context_text: str) -> AnalysisResult:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": context_text},
            ],
            "stream": False,
            # Ollama's JSON mode constrains output to syntactically valid JSON.
            # parse_json_response() still runs defensively on top of it, since
            # "valid JSON" doesn't guarantee our exact keys are all present.
            "format": "json",
            "options": {"temperature": 0.2},
        }
        data = json.dumps(payload).encode("utf-8")
        url = f"{self.host}/api/chat"

        last_err = None
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(
                url, data=data, method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                text = body.get("message", {}).get("content", "")
                parsed = parse_json_response(text, backend=self.name, model=self.model)
                parsed.input_tokens = body.get("prompt_eval_count", 0) or 0
                parsed.output_tokens = body.get("eval_count", 0) or 0
                return parsed
            except urllib.error.HTTPError as e:
                body_text = ""
                try:
                    body_text = e.read().decode("utf-8", "replace")
                except Exception:
                    pass
                last_err = f"HTTP {e.code} from Ollama: {body_text[:300] or e.reason}"
                if "model" in body_text.lower() and "not found" in body_text.lower():
                    return AnalysisResult.from_failure(
                        f"Model '{self.model}' isn't pulled yet. Run: ollama pull {self.model}",
                        backend=self.name, model=self.model,
                    )
            except urllib.error.URLError as e:
                last_err = (
                    f"Couldn't reach Ollama at {self.host} ({e.reason}). "
                    f"Is it running? Start it with `ollama serve`."
                )
            except Exception as e:  # noqa: BLE001
                last_err = str(e)

            if attempt < self.max_retries:
                time.sleep(min(2 ** attempt, 8))

        return AnalysisResult.from_failure(
            f"Ollama request failed after {self.max_retries + 1} attempt(s): {last_err}",
            backend=self.name, model=self.model,
        )

    def check_available(self) -> Optional[str]:
        """Lightweight preflight check: is the Ollama server reachable at all?
        Returns None if OK, or a human-readable error string if not. Called
        once up front so a whole batch of errors doesn't each wait out their
        own timeout before reporting the same 'server not running' problem."""
        req = urllib.request.Request(f"{self.host}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
            return None
        except urllib.error.URLError as e:
            return (f"Couldn't reach Ollama at {self.host} ({e.reason}). "
                    f"Is it running? Start it with `ollama serve`.")
        except Exception as e:  # noqa: BLE001
            return f"Couldn't reach Ollama at {self.host}: {e}"
