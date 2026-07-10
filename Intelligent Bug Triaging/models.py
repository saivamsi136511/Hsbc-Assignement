"""
models.py — Data models for Intelligent Bug Triaging System.

BugReport : raw user-submitted bug report (title + description)
Ticket    : fully triaged ticket with AI-assigned category, severity, priority, etc.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Severity / Priority constants
# ---------------------------------------------------------------------------

SEVERITIES = ("Critical", "High", "Medium", "Low")
PRIORITIES = ("P1", "P2", "P3", "P4")
STATUSES   = ("Open", "In Progress", "Resolved", "Closed", "Duplicate")

CATEGORIES = (
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

# Severity -> Priority mapping
SEVERITY_PRIORITY: Dict[str, str] = {
    "Critical": "P1",
    "High":     "P2",
    "Medium":   "P3",
    "Low":      "P4",
}


# ---------------------------------------------------------------------------
# BugReport — raw input from the user
# ---------------------------------------------------------------------------

@dataclass
class BugReport:
    """Raw bug report as submitted by a user."""

    title: str
    description: str
    submitter: str = "anonymous"
    submitted_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BugReport":
        return cls(
            title=d.get("title", ""),
            description=d.get("description", ""),
            submitter=d.get("submitter", "anonymous"),
            submitted_at=d.get("submitted_at", datetime.utcnow().isoformat()),
        )


# ---------------------------------------------------------------------------
# Ticket — fully triaged record stored in the database
# ---------------------------------------------------------------------------

@dataclass
class Ticket:
    """
    A bug report that has been processed by the triaging engine and saved
    to the database.  All AI-assigned fields have sensible defaults so the
    object can be constructed incrementally.
    """

    # Identity
    id: Optional[int] = None
    bug_id: str = ""

    # Raw report
    title: str = ""
    description: str = ""
    submitter: str = "anonymous"
    submitted_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # AI-assigned triaging fields
    category: str = "Unknown"
    severity: str = "Medium"
    priority: str = "P3"
    assigned_team: str = "Triage Team"
    confidence: int = 0

    # Urgency / sentiment
    urgency_score: int = 0
    urgency_level: str = "Low"

    # LLM-generated insights
    summary: str = ""
    suggested_fix: str = ""
    analysis_source: str = "heuristic"

    # Workflow
    status: str = "Open"
    duplicate_of: Optional[int] = None

    # Timestamps
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Ticket":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]

    @property
    def severity_color(self) -> str:
        return {
            "Critical": "#ff4757",
            "High":     "#ffa502",
            "Medium":   "#2ed573",
            "Low":      "#1e90ff",
        }.get(self.severity, "#888")

    @property
    def priority_badge(self) -> str:
        return {
            "P1": "🔴 P1",
            "P2": "🟠 P2",
            "P3": "🟡 P3",
            "P4": "🟢 P4",
        }.get(self.priority, self.priority)
