"""
domain/constants.py
===================
Centralized constants for the Intelligent Bug Triaging system.

All category lists, severity/priority mappings, team assignments, and other
domain constants are defined here. Import from this module rather than
duplicating values across the codebase.
"""

from typing import Dict, Tuple

# ---------------------------------------------------------------------------
# Bug categories
# ---------------------------------------------------------------------------

CATEGORIES: Tuple[str, ...] = (
    "UI",
    "Backend",
    "Database",
    "Authentication",
    "Security",
    "Performance",
    "Network",
    "Mobile",
    "Infrastructure",
    "Unknown",
)
"""All valid bug categories the triaging engine can assign."""

# ---------------------------------------------------------------------------
# Severity levels (ordered from most to least severe)
# ---------------------------------------------------------------------------

SEVERITIES: Tuple[str, ...] = ("Critical", "High", "Medium", "Low")
"""All valid severity levels, ordered from most to least severe."""

# ---------------------------------------------------------------------------
# Priority levels (ordered from most to least urgent)
# ---------------------------------------------------------------------------

PRIORITIES: Tuple[str, ...] = ("P1", "P2", "P3", "P4")
"""
Priority labels:
  P1 — Blocker / Critical (must fix immediately)
  P2 — High (fix in current sprint)
  P3 — Medium (fix in next sprint)
  P4 — Low / Nice-to-have
"""

# ---------------------------------------------------------------------------
# Ticket lifecycle statuses
# ---------------------------------------------------------------------------

STATUSES: Tuple[str, ...] = ("Open", "In Progress", "Resolved", "Closed", "Duplicate")
"""All valid ticket workflow statuses."""

# ---------------------------------------------------------------------------
# Severity → Priority mapping
# ---------------------------------------------------------------------------

SEVERITY_PRIORITY: Dict[str, str] = {
    "Critical": "P1",
    "High":     "P2",
    "Medium":   "P3",
    "Low":      "P4",
}
"""Maps a severity level to its corresponding default priority."""

# ---------------------------------------------------------------------------
# Category → Team mapping
# ---------------------------------------------------------------------------

TEAM_MAP: Dict[str, str] = {
    "UI":             "Frontend Team",
    "Backend":        "Backend Team",
    "Database":       "Database Team",
    "Authentication": "Auth & Identity Team",
    "Security":       "Security Team",
    "Performance":    "Platform Team",
    "Network":        "Network/Infra Team",
    "Mobile":         "Mobile Team",
    "Infrastructure": "DevOps Team",
    "Unknown":        "Triage Team",
}
"""Maps a bug category to the engineering team responsible for that area."""

# ---------------------------------------------------------------------------
# LLM provider options
# ---------------------------------------------------------------------------

PROVIDERS: Tuple[str, ...] = ("ollama", "openai", "none")
"""Supported LLM provider backends for the triaging engine."""

DEFAULT_PROVIDER: str = "ollama"
"""Default LLM provider (local Ollama — no API key or cost required)."""

DEFAULT_MODEL: str = "llama3.1"
"""Default Ollama model used for AI-powered triage."""

DEFAULT_OLLAMA_URL: str = "http://localhost:11434"
"""Default base URL for the local Ollama server."""

DEFAULT_LLM_TIMEOUT: int = 60
"""Seconds to wait for a single LLM triage response before timing out."""

# ---------------------------------------------------------------------------
# Flask server defaults
# ---------------------------------------------------------------------------

DEFAULT_HOST: str = "0.0.0.0"
"""Host the Flask application listens on (0.0.0.0 = all interfaces)."""

DEFAULT_PORT: int = 5000
"""Port the Flask dashboard runs on by default."""

# ---------------------------------------------------------------------------
# Database defaults
# ---------------------------------------------------------------------------

DEFAULT_DB_FILENAME: str = "bugs.db"
"""Default SQLite database filename (relative to the project directory)."""

# ---------------------------------------------------------------------------
# Severity colour codes (used in dashboard UI and model response)
# ---------------------------------------------------------------------------

SEVERITY_COLORS: Dict[str, str] = {
    "Critical": "#ff4757",
    "High":     "#ffa502",
    "Medium":   "#2ed573",
    "Low":      "#1e90ff",
}
"""Hex colour codes for each severity level, used in the web dashboard."""

# ---------------------------------------------------------------------------
# Priority badge emojis (used in display / reporting)
# ---------------------------------------------------------------------------

PRIORITY_BADGES: Dict[str, str] = {
    "P1": "🔴 P1",
    "P2": "🟠 P2",
    "P3": "🟡 P3",
    "P4": "🟢 P4",
}
"""Display labels with colour emoji for each priority level."""

# ---------------------------------------------------------------------------
# Confidence scoring bounds
# ---------------------------------------------------------------------------

MIN_CONFIDENCE: int = 0
MAX_CONFIDENCE: int = 100
BASE_CONFIDENCE: int = 40
"""Heuristic base confidence score when a category is matched."""

CONFIDENCE_PER_SIGNAL: int = 10
"""Confidence points added per additional matching keyword signal."""

UNKNOWN_CONFIDENCE: int = 20
"""Confidence score when the category is 'Unknown' (no signals found)."""

# ---------------------------------------------------------------------------
# Duplicate detection settings
# ---------------------------------------------------------------------------

DUPLICATE_TITLE_SIMILARITY_THRESHOLD: float = 0.85
"""Minimum similarity score (0–1) for two titles to be flagged as duplicates."""
