"""
api/routes.py
=============
Flask route definitions for the Intelligent Bug Triaging REST API and dashboard.

All HTTP endpoints are defined here. This module is imported by ``app.py``
(the application factory) and registered on the Flask app instance.

Endpoints
---------
GET  /                      Web dashboard (HTML)
POST /api/bugs              Submit a new bug report for triaging
GET  /api/bugs              List all tickets (supports filtering & pagination)
GET  /api/bugs/<id>         Retrieve a single ticket by ID
PATCH /api/bugs/<id>        Update ticket fields (status, priority, etc.)
DELETE /api/bugs/<id>       Delete a ticket
GET  /api/bugs/search?q=    Full-text search across all tickets
GET  /api/stats             Dashboard statistics (counts by category/severity)
GET  /api/health            Health check (LLM provider status + timestamp)

This module is a documentation reference. The canonical implementations
live in ``app.py`` (the original flat file), which this package re-exports
for backward compatibility.
"""

# Re-export the Flask app factory from the canonical flat module.
try:
    from app import create_app
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from app import create_app

__all__ = ["create_app"]
