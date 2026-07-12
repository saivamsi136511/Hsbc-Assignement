"""
domain/models.py
================
Core data models for the Intelligent Bug Triaging system.

Defines the two primary domain objects:
- ``BugReport`` — the raw, unprocessed bug report as submitted by a user.
- ``Ticket``    — a fully triaged ticket with all AI-assigned fields, ready
                  for storage in the database and display in the dashboard.

These models are intentionally kept dependency-free (only Python standard
library imports) so that they can be imported anywhere in the package
without pulling in Flask, SQLite, or ML dependencies.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from domain.constants import (
    CATEGORIES,
    SEVERITY_COLORS,
    PRIORITY_BADGES,
    SEVERITY_PRIORITY,
    TEAM_MAP,
)


@dataclass
class BugReport:
    """
    Raw bug report as submitted by a user, before any AI triaging.

    This is an immutable snapshot of the user's input.  It is passed to the
    ``TriagingEngine`` and never mutated after creation.

    Attributes:
        title:        Short, human-readable summary of the bug (required).
        description:  Full description of the issue, steps to reproduce,
                      observed vs expected behaviour, etc. (required).
        submitter:    Username or email of the person who submitted the report.
                      Defaults to ``"anonymous"`` when not provided.
        submitted_at: ISO-8601 timestamp of when the report was received.
                      Auto-populated to ``datetime.utcnow()`` when omitted.
    """

    title: str
    description: str
    submitter: str = "anonymous"
    submitted_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialise the BugReport to a plain dictionary.

        Returns:
            A dict representation suitable for JSON serialisation.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BugReport":
        """
        Deserialise a BugReport from a plain dictionary.

        Args:
            d: Dictionary with keys matching the dataclass field names.
               Missing keys are filled with their defaults.

        Returns:
            A new ``BugReport`` instance.
        """
        return cls(
            title=d.get("title", ""),
            description=d.get("description", ""),
            submitter=d.get("submitter", "anonymous"),
            submitted_at=d.get("submitted_at", datetime.utcnow().isoformat()),
        )


@dataclass
class Ticket:
    """
    A fully triaged bug ticket stored in the database.

    Created by the ``TriagingEngine`` from a ``BugReport``.  All AI-assigned
    fields have sensible defaults so the object can be built incrementally
    (e.g. starting with heuristics then enriched by an LLM response).

    Attributes:
        id:              Auto-assigned integer primary key (set after DB insert).
        bug_id:          Human-readable ticket ID (e.g. ``"BUG-0042"``).
        title:           Bug report title.
        description:     Bug report description.
        submitter:       Username/email of the submitter.
        submitted_at:    ISO-8601 timestamp from the original report.
        category:        AI-assigned category (e.g. ``"Backend"``, ``"UI"``).
        severity:        AI-assigned severity (``Critical`` / ``High`` / ``Medium`` / ``Low``).
        priority:        Derived priority from severity (``P1``–``P4``).
        assigned_team:   Engineering team responsible for this category.
        confidence:      0–100 score representing the AI's certainty.
        urgency_score:   0–100 raw urgency score from heuristic keyword analysis.
        urgency_level:   Human-readable urgency tier derived from urgency_score.
        summary:         1–2 sentence plain-English summary (LLM-generated).
        suggested_fix:   Concrete, actionable suggestion for investigation or fix.
        analysis_source: Which engine produced the triage (``"heuristic"`` or ``"LLM (<model>)"``).
        status:          Lifecycle status (``Open`` / ``In Progress`` / etc.).
        duplicate_of:    ID of the ticket this duplicates, if detected.
        updated_at:      ISO-8601 timestamp of last modification.
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

    # Urgency / sentiment analysis
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
        """
        Serialise the Ticket to a plain dictionary for JSON responses.

        Returns:
            A dict representation of all ticket fields.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Ticket":
        """
        Deserialise a Ticket from a plain dictionary (e.g. from a database row).

        Args:
            d: Dictionary with keys matching the dataclass field names.
               Unknown keys are silently ignored.

        Returns:
            A new ``Ticket`` instance.
        """
        valid_fields = cls.__dataclass_fields__  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in valid_fields})

    @property
    def severity_color(self) -> str:
        """
        Hex colour code for this ticket's severity level.

        Returns:
            A CSS hex colour string (e.g. ``"#ff4757"`` for Critical).
            Falls back to ``"#888"`` for unknown severities.
        """
        return SEVERITY_COLORS.get(self.severity, "#888")

    @property
    def priority_badge(self) -> str:
        """
        Emoji-prefixed priority label for display in the dashboard.

        Returns:
            A string like ``"🔴 P1"`` or ``"🟢 P4"``.
        """
        return PRIORITY_BADGES.get(self.priority, self.priority)
