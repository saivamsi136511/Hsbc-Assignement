"""
api/errors.py
=============
Standardised error response helpers for the Bug Triaging Flask API.

Provides a consistent JSON error envelope format for all API error responses
so that clients can rely on a predictable ``{"error": "<message>"}`` shape.

Usage
-----
    from api.errors import api_error, not_found, bad_request

    return not_found(f"Ticket {ticket_id} not found")
    return bad_request("'title' field is required")
"""

from typing import Tuple

from flask import Response, jsonify


def api_error(message: str, status_code: int = 400) -> Tuple[Response, int]:
    """
    Build a standardised JSON error response.

    Args:
        message:     Human-readable error description to include in the response body.
        status_code: HTTP status code for the response (default: 400 Bad Request).

    Returns:
        A tuple of ``(flask.Response, int)`` ready to be returned from a route handler.
        The response body is ``{"error": "<message>"}`` with the given status code.
    """
    return jsonify({"error": message}), status_code


def bad_request(message: str) -> Tuple[Response, int]:
    """
    Return a 400 Bad Request error response.

    Args:
        message: Description of why the request was malformed.

    Returns:
        ``(Response, 400)`` JSON error tuple.
    """
    return api_error(message, 400)


def not_found(message: str) -> Tuple[Response, int]:
    """
    Return a 404 Not Found error response.

    Args:
        message: Description of what was not found (e.g. ticket ID).

    Returns:
        ``(Response, 404)`` JSON error tuple.
    """
    return api_error(message, 404)


def server_error(message: str) -> Tuple[Response, int]:
    """
    Return a 500 Internal Server Error response.

    Args:
        message: Description of the internal error (avoid leaking stack traces).

    Returns:
        ``(Response, 500)`` JSON error tuple.
    """
    return api_error(message, 500)
