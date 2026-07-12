"""
repositories/ticket_repository.py
==================================
SQLite-backed repository for Ticket CRUD operations.

This module is a thin wrapper around the existing ``database.py`` module,
exposing the same ``TicketDB`` interface through the new package structure
so that new code can import from the layered architecture while the original
flat file continues to work for backward compatibility.

Usage
-----
    from repositories.ticket_repository import TicketRepository

    repo = TicketRepository("bugs.db")
    ticket = repo.create(ticket_obj)
    tickets = repo.list_all(category="Backend", severity="High")
"""

# Re-export from the existing flat module for backward compatibility.
# The original database.py remains the canonical implementation; this
# module simply exposes it under the new package path.
try:
    from database import TicketDB as TicketRepository
except ImportError:
    # Allow the package to be imported even when run from a different CWD
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from database import TicketDB as TicketRepository

__all__ = ["TicketRepository"]
