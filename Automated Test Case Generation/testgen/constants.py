"""
testgen/constants.py
====================
Centralized constants for the Automated Test Case Generation package.

All magic strings, numeric defaults, and configuration values used across
the testgen package are defined here so they can be changed in one place.
"""

# ---------------------------------------------------------------------------
# Ollama server defaults
# ---------------------------------------------------------------------------

OLLAMA_DEFAULT_HOST: str = "http://localhost:11434"
"""Default base URL for the locally running Ollama server."""

OLLAMA_API_CHAT_PATH: str = "/api/chat"
"""REST path for Ollama's chat completion endpoint."""

# ---------------------------------------------------------------------------
# Model defaults
# ---------------------------------------------------------------------------

DEFAULT_MODEL: str = "llama3.1"
"""Default Ollama model name used when none is specified by the user."""

RECOMMENDED_MODEL: str = "qwen2.5-coder:7b"
"""Recommended code-focused model for the best test-generation quality."""

# ---------------------------------------------------------------------------
# Generation defaults
# ---------------------------------------------------------------------------

DEFAULT_TEMPERATURE: float = 0.2
"""Sampling temperature. Kept low for deterministic, reproducible test code."""

DEFAULT_NUM_CTX: int = 8192
"""Context window size (tokens) requested from Ollama."""

DEFAULT_NUM_PREDICT: int = -1
"""Max tokens to generate; -1 means generate until the model's natural stop."""

DEFAULT_MAX_RETRIES: int = 2
"""Number of self-healing attempts if generated code has a syntax error."""

# ---------------------------------------------------------------------------
# Batching defaults
# ---------------------------------------------------------------------------

DEFAULT_BATCH_SIZE: int = 8
"""Maximum number of acceptance criteria processed per batch in batch mode."""

DEFAULT_BATCH_THRESHOLD: int = 10
"""Stories with more numbered items than this trigger automatic batch mode."""

# ---------------------------------------------------------------------------
# HTTP timeout defaults
# ---------------------------------------------------------------------------

DEFAULT_CONNECT_TIMEOUT: int = 10
"""Seconds to wait for the initial TCP connection to Ollama."""

DEFAULT_READ_TIMEOUT: int = 60
"""Seconds of silence allowed between streamed tokens before treating as stall."""

DEFAULT_MAX_CONN_RETRIES: int = 3
"""Number of reconnection attempts on connection/timeout errors."""

BACKOFF_BASE_SECONDS: int = 2
"""Initial backoff delay in seconds; doubles on each subsequent retry."""

# ---------------------------------------------------------------------------
# Output file defaults
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_FILE: str = "test_generated.py"
"""Default filename for the generated PyTest test module."""

STUB_FILENAME: str = "solution.py"
"""Preferred filename for the generated solution stub."""

STUB_FALLBACK_FILENAME: str = "solution_stub.py"
"""Fallback filename for the stub when solution.py already exists."""

# ---------------------------------------------------------------------------
# Code extraction
# ---------------------------------------------------------------------------

CODE_FENCE_PATTERN: str = r"```(?:python)?\s*\n(.*?)```"
"""Regex pattern for extracting Python code from a fenced markdown block."""

# ---------------------------------------------------------------------------
# Acceptance-criteria splitting
# ---------------------------------------------------------------------------

NUMBERED_ITEM_PATTERN: str = r"^[ \t]*(\d{1,3})\.[ \t]+"
"""Regex pattern to detect numbered acceptance-criteria items (e.g. '1. ...')."""

# ---------------------------------------------------------------------------
# Test-summary regex patterns
# ---------------------------------------------------------------------------

PATTERN_TEST_FUNC: str = r"^\s*def test_"
PATTERN_HAPPY_PATH: str = r"#\s*-+\s*Happy path"
PATTERN_BOUNDARY: str = r"#\s*-+\s*Boundary value"
PATTERN_EDGE_CASE: str = r"#\s*-+\s*Edge cases"
PATTERN_ERROR_HANDLING: str = r"#\s*-+\s*Error handling"
PATTERN_PARAMETRIZE: str = r"@pytest\.mark\.parametrize"

# ---------------------------------------------------------------------------
# Python built-ins excluded from 'from solution import' detection
# ---------------------------------------------------------------------------

PYTHON_BUILTINS: frozenset = frozenset({
    'print', 'range', 'len', 'str', 'int', 'float', 'bool', 'dict', 'list',
    'set', 'tuple', 'isinstance', 'type', 'callable', 'sum', 'min', 'max',
    'sorted', 'reversed', 'enumerate', 'zip', 'map', 'filter', 'any', 'all',
    'open', 'input', 'format', 'abs', 'round', 'pow', 'divmod', 'hash',
    'hex', 'oct', 'bin', 'chr', 'ord', 'eval', 'exec', 'compile', 'vars',
    'dir', 'getattr', 'setattr', 'hasattr', 'delattr', 'property', 'classmethod',
    'staticmethod', 'super', 'object', 'Exception', 'BaseException', 'ValueError',
    'TypeError', 'KeyError', 'IndexError', 'AttributeError', 'IOError',
})
"""Python built-in names that should never be auto-imported from solution.py."""
