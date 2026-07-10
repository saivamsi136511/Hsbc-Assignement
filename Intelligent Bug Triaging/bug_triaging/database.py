"""
database.py — SQLite-backed ticket store for Intelligent Bug Triaging System.

Provides:
  - create_ticket()      — insert a new fully-triaged ticket
  - get_ticket()         — fetch by numeric id
  - list_tickets()       — list with optional filters
  - update_ticket()      — partial update
  - search_tickets()     — full-text search on title + description + summary
  - find_duplicates()    — similarity check against open tickets
  - get_stats()          — aggregate counts for the dashboard
  - delete_ticket()      — hard delete

No third-party packages required — uses only sqlite3 (stdlib).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from models import Ticket

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "bugs.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bug_id          TEXT    NOT NULL UNIQUE,
    title           TEXT    NOT NULL,
    description     TEXT    NOT NULL,
    submitter       TEXT    NOT NULL DEFAULT 'anonymous',
    submitted_at    TEXT    NOT NULL,
    category        TEXT    NOT NULL DEFAULT 'Unknown',
    severity        TEXT    NOT NULL DEFAULT 'Medium',
    priority        TEXT    NOT NULL DEFAULT 'P3',
    assigned_team   TEXT    NOT NULL DEFAULT 'Triage Team',
    confidence      INTEGER NOT NULL DEFAULT 0,
    urgency_score   INTEGER NOT NULL DEFAULT 0,
    urgency_level   TEXT    NOT NULL DEFAULT 'Low',
    summary         TEXT    NOT NULL DEFAULT '',
    suggested_fix   TEXT    NOT NULL DEFAULT '',
    analysis_source TEXT    NOT NULL DEFAULT 'heuristic',
    status          TEXT    NOT NULL DEFAULT 'Open',
    duplicate_of    INTEGER,
    updated_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_category  ON tickets(category);
CREATE INDEX IF NOT EXISTS idx_severity  ON tickets(severity);
CREATE INDEX IF NOT EXISTS idx_priority  ON tickets(priority);
CREATE INDEX IF NOT EXISTS idx_status    ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_submitted ON tickets(submitted_at);
"""


class TicketDB:
    """Thin wrapper around an SQLite connection."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(_SCHEMA)
        conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _row_to_ticket(self, row: sqlite3.Row) -> Ticket:
        d = dict(row)
        return Ticket(**{k: d[k] for k in Ticket.__dataclass_fields__ if k in d})  # type: ignore[attr-defined]

    def _next_bug_id(self, conn: sqlite3.Connection) -> str:
        row = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()
        seq = (row[0] or 0) + 1
        return f"BUG-{seq:04d}"

    # ---- CRUD ---------------------------------------------------------------

    def create_ticket(self, ticket: Ticket) -> Ticket:
        conn = self._get_conn()
        now = datetime.utcnow().isoformat()
        bug_id = ticket.bug_id or self._next_bug_id(conn)

        conn.execute(
            """
            INSERT INTO tickets
              (bug_id, title, description, submitter, submitted_at,
               category, severity, priority, assigned_team, confidence,
               urgency_score, urgency_level, summary, suggested_fix,
               analysis_source, status, duplicate_of, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                bug_id, ticket.title, ticket.description,
                ticket.submitter, ticket.submitted_at or now,
                ticket.category, ticket.severity, ticket.priority,
                ticket.assigned_team, ticket.confidence,
                ticket.urgency_score, ticket.urgency_level,
                ticket.summary, ticket.suggested_fix,
                ticket.analysis_source, ticket.status,
                ticket.duplicate_of, now,
            ),
        )
        conn.commit()
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return self.get_ticket(row_id)  # type: ignore[return-value]

    def get_ticket(self, ticket_id: int) -> Optional[Ticket]:
        row = self._get_conn().execute(
            "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
        return self._row_to_ticket(row) if row else None

    def get_ticket_by_bug_id(self, bug_id: str) -> Optional[Ticket]:
        row = self._get_conn().execute(
            "SELECT * FROM tickets WHERE bug_id = ?", (bug_id,)
        ).fetchone()
        return self._row_to_ticket(row) if row else None

    def list_tickets(
        self,
        category: Optional[str] = None,
        severity: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Ticket]:
        clauses: List[str] = []
        params: List[Any] = []

        if category:
            clauses.append("category = ?"); params.append(category)
        if severity:
            clauses.append("severity = ?"); params.append(severity)
        if priority:
            clauses.append("priority = ?"); params.append(priority)
        if status:
            clauses.append("status = ?"); params.append(status)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params += [limit, offset]

        rows = self._get_conn().execute(
            f"SELECT * FROM tickets {where} ORDER BY submitted_at DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [self._row_to_ticket(r) for r in rows]

    def update_ticket(self, ticket_id: int, updates: Dict[str, Any]) -> Optional[Ticket]:
        allowed = {
            "status", "priority", "severity", "category",
            "assigned_team", "duplicate_of", "summary", "suggested_fix",
        }
        safe = {k: v for k, v in updates.items() if k in allowed}
        if not safe:
            return self.get_ticket(ticket_id)

        safe["updated_at"] = datetime.utcnow().isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in safe)
        params = list(safe.values()) + [ticket_id]

        conn = self._get_conn()
        conn.execute(f"UPDATE tickets SET {set_clause} WHERE id = ?", params)
        conn.commit()
        return self.get_ticket(ticket_id)

    def delete_ticket(self, ticket_id: int) -> bool:
        conn = self._get_conn()
        cur = conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
        conn.commit()
        return cur.rowcount > 0

    # ---- Search -------------------------------------------------------------

    def search_tickets(self, query: str, limit: int = 100) -> List[Ticket]:
        like = f"%{query}%"
        rows = self._get_conn().execute(
            """
            SELECT * FROM tickets
            WHERE title LIKE ? OR description LIKE ? OR summary LIKE ?
            ORDER BY submitted_at DESC LIMIT ?
            """,
            (like, like, like, limit),
        ).fetchall()
        return [self._row_to_ticket(r) for r in rows]

    # ---- Duplicate detection -------------------------------------------------

    def find_duplicates(
        self, title: str, description: str, threshold: float = 0.35
    ) -> List[Ticket]:
        import re

        _STOP = {
            "the", "a", "an", "is", "it", "in", "on", "at", "to", "for",
            "of", "and", "or", "but", "not", "with", "this", "that", "are",
            "was", "be", "has", "have", "had", "by", "from", "we", "i",
            "can", "cannot", "do", "does", "did", "will", "would", "should",
            "could", "may", "might", "get", "got", "our", "my", "your",
        }

        def tokenize(text: str):
            return set(re.findall(r"[a-z0-9]+", text.lower())) - _STOP

        incoming_tokens = tokenize(title + " " + description)
        if not incoming_tokens:
            return []

        candidates = self.list_tickets(status="Open") + self.list_tickets(status="In Progress")
        duplicates: List[Ticket] = []

        for t in candidates:
            candidate_tokens = tokenize(t.title + " " + t.description)
            if not candidate_tokens:
                continue
            intersection = incoming_tokens & candidate_tokens
            union = incoming_tokens | candidate_tokens
            jaccard = len(intersection) / len(union)
            if jaccard >= threshold:
                duplicates.append(t)

        return duplicates

    # ---- Stats --------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        conn = self._get_conn()

        total = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        open_count = conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE status = 'Open'"
        ).fetchone()[0]

        by_category = {
            row["category"]: row["cnt"]
            for row in conn.execute(
                "SELECT category, COUNT(*) as cnt FROM tickets GROUP BY category ORDER BY cnt DESC"
            ).fetchall()
        }
        by_severity = {
            row["severity"]: row["cnt"]
            for row in conn.execute(
                "SELECT severity, COUNT(*) as cnt FROM tickets GROUP BY severity"
            ).fetchall()
        }
        by_priority = {
            row["priority"]: row["cnt"]
            for row in conn.execute(
                "SELECT priority, COUNT(*) as cnt FROM tickets GROUP BY priority ORDER BY priority"
            ).fetchall()
        }
        by_status = {
            row["status"]: row["cnt"]
            for row in conn.execute(
                "SELECT status, COUNT(*) as cnt FROM tickets GROUP BY status"
            ).fetchall()
        }

        recent = conn.execute(
            "SELECT * FROM tickets ORDER BY submitted_at DESC LIMIT 5"
        ).fetchall()

        return {
            "total": total,
            "open": open_count,
            "by_category": by_category,
            "by_severity": by_severity,
            "by_priority": by_priority,
            "by_status": by_status,
            "recent": [dict(r) for r in recent],
        }
