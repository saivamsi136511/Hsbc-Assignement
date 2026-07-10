#!/usr/bin/env python3
"""
seed_bugs.py — Load sample bug reports into the Bug Triaging system.

Usage:
    python seed_bugs.py                      # Use sample_bugs.json
    python seed_bugs.py --file my_bugs.json  # Use a custom file
    python seed_bugs.py --clear              # Clear existing tickets first

Run this while the app is NOT running (it writes directly to the DB),
OR after starting the app and use --api to submit via HTTP.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(__file__))


def seed_via_api(bugs: list, base_url: str) -> None:
    """Submit bugs through the running HTTP API."""
    print(f"Submitting {len(bugs)} bugs to {base_url}/api/bugs ...\n")
    for i, bug in enumerate(bugs, 1):
        data = json.dumps(bug).encode("utf-8")
        req  = urllib.request.Request(
            f"{base_url}/api/bugs",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
                t = result["ticket"]
                dup = " [DUPLICATE]" if result.get("is_duplicate") else ""
                print(
                    f"  [{i:2d}] {t['bug_id']}{dup}  "
                    f"{t['severity']:8s} | {t['priority']} | {t['category']:15s} | {t['assigned_team']}"
                )
        except urllib.error.URLError as e:
            print(f"  [{i:2d}] FAILED: {e}")


def seed_direct(bugs: list, db_path: str, clear: bool) -> None:
    """Write directly to the SQLite database (app must not be running)."""
    from database import TicketDB
    from triaging_engine import TriagingEngine
    from models import BugReport

    db     = TicketDB(db_path)
    engine = TriagingEngine(provider="none")

    if clear:
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM tickets")
        conn.commit()
        conn.close()
        print("Cleared existing tickets.\n")

    print(f"Seeding {len(bugs)} bugs (heuristic mode)...\n")
    for i, bug in enumerate(bugs, 1):
        report = BugReport(
            title       = bug.get("title", ""),
            description = bug.get("description", ""),
            submitter   = bug.get("submitter", "seed-script"),
        )
        ticket = engine.triage(report)
        saved  = db.create_ticket(ticket)
        print(
            f"  [{i:2d}] {saved.bug_id}  "
            f"{saved.severity:8s} | {saved.priority} | {saved.category:15s} | {saved.assigned_team}"
        )


def main():
    p = argparse.ArgumentParser(description="Seed sample bug reports into the triaging system")
    p.add_argument("--file",  default=os.path.join(os.path.dirname(__file__), "sample_bugs.json"))
    p.add_argument("--api",   default=None, help="Submit via HTTP API (e.g. http://localhost:5000)")
    p.add_argument("--db",    default=os.path.join(os.path.dirname(__file__), "bugs.db"))
    p.add_argument("--clear", action="store_true", help="Clear existing tickets before seeding")
    args = p.parse_args()

    with open(args.file, encoding="utf-8") as f:
        bugs = json.load(f)

    if args.api:
        seed_via_api(bugs, args.api.rstrip("/"))
    else:
        seed_direct(bugs, args.db, args.clear)

    print("\nDone! All bugs seeded successfully.")


if __name__ == "__main__":
    main()
