"""
app.py — Flask REST API + dashboard server for Intelligent Bug Triaging System.

Endpoints:
  POST   /api/bugs              Submit new bug report
  GET    /api/bugs              List all tickets (filterable)
  GET    /api/bugs/<id>         Get single ticket
  PATCH  /api/bugs/<id>         Update ticket fields
  DELETE /api/bugs/<id>         Delete ticket
  GET    /api/bugs/search?q=    Full-text search
  GET    /api/stats             Dashboard statistics
  GET    /                      Dashboard HTML

Run:
  pip install flask
  python app.py
  python app.py --provider ollama --model llama3.1   # with LLM
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Any, Dict, Tuple

from flask import Flask, Response, jsonify, render_template, request

sys.path.insert(0, os.path.dirname(__file__))

from models import BugReport, Ticket
from database import TicketDB
from triaging_engine import TriagingEngine


def create_app(
    provider:   str = "ollama",
    model:      str = "llama3.1",
    ollama_url: str = "http://localhost:11434",
    api_base:   str = None,
    api_key:    str = "",
    timeout:    int = 60,
    db_path:    str = None,
):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["JSON_SORT_KEYS"] = False

    db_path = db_path or os.path.join(os.path.dirname(__file__), "bugs.db")
    db      = TicketDB(db_path)
    engine  = TriagingEngine(
        provider=provider, model=model,
        ollama_url=ollama_url, api_base=api_base,
        api_key=api_key, timeout=timeout,
    )

    def _ticket_json(t: Ticket) -> Dict[str, Any]:
        return t.to_dict()

    def _error(msg: str, code: int = 400) -> Tuple[Response, int]:
        return jsonify({"error": msg}), code

    def _ok(data: Any, code: int = 200) -> Tuple[Response, int]:
        return jsonify(data), code

    @app.after_request
    def _cors(response):
        response.headers["Access-Control-Allow-Origin"]  = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,PATCH,DELETE,OPTIONS"
        return response

    @app.route("/api/<path:path>", methods=["OPTIONS"])
    def _options(path):
        return "", 204

    @app.route("/")
    def dashboard():
        return render_template("index.html")

    @app.route("/api/bugs", methods=["POST"])
    def submit_bug():
        body = request.get_json(silent=True)
        if not body:
            return _error("Request body must be JSON")

        title       = (body.get("title") or "").strip()
        description = (body.get("description") or "").strip()
        submitter   = (body.get("submitter") or "anonymous").strip()

        if not title:
            return _error("'title' is required")
        if not description:
            return _error("'description' is required")

        report = BugReport(title=title, description=description, submitter=submitter)

        duplicates   = db.find_duplicates(title, description)
        duplicate_of = duplicates[0].id if duplicates else None

        ticket = engine.triage(report)
        ticket.duplicate_of = duplicate_of
        if duplicate_of:
            ticket.status = "Duplicate"

        saved = db.create_ticket(ticket)

        response_data = {
            "ticket":       _ticket_json(saved),
            "is_duplicate": duplicate_of is not None,
        }
        if duplicate_of:
            response_data["duplicate_of"] = _ticket_json(duplicates[0])

        return _ok(response_data, 201)

    @app.route("/api/bugs", methods=["GET"])
    def list_bugs():
        category = request.args.get("category")
        severity = request.args.get("severity")
        priority = request.args.get("priority")
        status   = request.args.get("status")
        limit    = min(int(request.args.get("limit", 200)), 500)
        offset   = int(request.args.get("offset", 0))

        tickets = db.list_tickets(
            category=category, severity=severity,
            priority=priority, status=status,
            limit=limit, offset=offset,
        )
        return _ok({"tickets": [_ticket_json(t) for t in tickets], "count": len(tickets)})

    @app.route("/api/bugs/search", methods=["GET"])
    def search_bugs():
        q = (request.args.get("q") or "").strip()
        if not q:
            return _error("Query parameter 'q' is required")
        tickets = db.search_tickets(q)
        return _ok({"tickets": [_ticket_json(t) for t in tickets], "count": len(tickets), "query": q})

    @app.route("/api/bugs/<int:ticket_id>", methods=["GET"])
    def get_bug(ticket_id: int):
        ticket = db.get_ticket(ticket_id)
        if not ticket:
            return _error(f"Ticket {ticket_id} not found", 404)
        return _ok(_ticket_json(ticket))

    @app.route("/api/bugs/<int:ticket_id>", methods=["PATCH"])
    def update_bug(ticket_id: int):
        body    = request.get_json(silent=True) or {}
        updated = db.update_ticket(ticket_id, body)
        if not updated:
            return _error(f"Ticket {ticket_id} not found", 404)
        return _ok(_ticket_json(updated))

    @app.route("/api/bugs/<int:ticket_id>", methods=["DELETE"])
    def delete_bug(ticket_id: int):
        deleted = db.delete_ticket(ticket_id)
        if not deleted:
            return _error(f"Ticket {ticket_id} not found", 404)
        return _ok({"deleted": True, "id": ticket_id})

    @app.route("/api/stats", methods=["GET"])
    def get_stats():
        return _ok(db.get_stats())

    @app.route("/api/health", methods=["GET"])
    def health():
        return _ok({
            "status":   "ok",
            "provider": provider,
            "model":    model,
            "time":     datetime.utcnow().isoformat(),
        })

    return app, db


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Intelligent Bug Triaging System — Flask API + Dashboard")
    p.add_argument("--provider", choices=["ollama", "openai", "none"], default="ollama")
    p.add_argument("--model",    default="llama3.1")
    p.add_argument("--ollama-url", default="http://localhost:11434")
    p.add_argument("--api-base", default=None)
    p.add_argument("--api-key",  default=os.environ.get("OPENAI_API_KEY", ""))
    p.add_argument("--timeout",  type=int, default=60)
    p.add_argument("--port",     type=int, default=5000)
    p.add_argument("--host",     default="0.0.0.0")
    p.add_argument("--db",       default=None)
    p.add_argument("--debug",    action="store_true")
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()

    print("=" * 60)
    print("  Intelligent Bug Triaging System")
    print("=" * 60)
    print(f"  LLM provider : {args.provider}")
    if args.provider == "ollama":
        print(f"  Ollama URL   : {args.ollama_url}")
    print(f"  Model        : {args.model}")
    print(f"  Dashboard    : http://localhost:{args.port}")
    print(f"  API base     : http://localhost:{args.port}/api")
    print("=" * 60)

    app, db = create_app(
        provider   = args.provider,
        model      = args.model,
        ollama_url = args.ollama_url,
        api_base   = args.api_base,
        api_key    = args.api_key,
        timeout    = args.timeout,
        db_path    = args.db,
    )

    app.run(host=args.host, port=args.port, debug=args.debug)
