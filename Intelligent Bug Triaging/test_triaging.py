#!/usr/bin/env python3
"""Quick test of the bug triaging engine."""

import sys

# Force UTF-8 stdout/stderr on Windows to avoid cp1252 codec errors
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from triaging_engine import TriagingEngine
from models import BugReport

engine = TriagingEngine(provider='none')

# Test case 1: Critical production outage
report1 = BugReport(
    title='Login button returns HTTP 500 — all production users locked out',
    description='Since 3:00 PM deployment, every user gets HTTP 500. NullPointerException in AuthService. Production outage affecting 100% of users.',
    submitter='ops-team'
)
ticket1 = engine.triage(report1)
print("=== TEST 1: Critical Production Outage ===")
print(f"Category: {ticket1.category}")
print(f"Severity: {ticket1.severity}")
print(f"Priority: {ticket1.priority}")
print(f"Urgency Score: {ticket1.urgency_score}")
print(f"Team: {ticket1.assigned_team}")
print(f"Confidence: {ticket1.confidence}%")
print()

# Test case 2: Mobile UI bug
report2 = BugReport(
    title='Dropdown menu overlaps content on mobile Safari',
    description='On iOS Safari, navigation dropdown overlaps content in portrait mode. Affects 15% of mobile users. Can scroll as workaround.',
    submitter='qa-team'
)
ticket2 = engine.triage(report2)
print("=== TEST 2: Mobile UI Bug ===")
print(f"Category: {ticket2.category}")
print(f"Severity: {ticket2.severity}")
print(f"Priority: {ticket2.priority}")
print(f"Team: {ticket2.assigned_team}")
print()

# Test case 3: Security vulnerability
report3 = BugReport(
    title='SQL injection vulnerability in search endpoint',
    description='The /api/search endpoint concatenates user input into SQL queries without parameterization. Confirmed malicious extraction possible.',
    submitter='security-audit'
)
ticket3 = engine.triage(report3)
print("=== TEST 3: Security Vulnerability ===")
print(f"Category: {ticket3.category}")
print(f"Severity: {ticket3.severity}")
print(f"Priority: {ticket3.priority}")
print(f"Team: {ticket3.assigned_team}")
print()

# Test case 4: Minor cosmetic bug
report4 = BugReport(
    title='Wrong currency symbol displayed for EUR users',
    description='Users with locale de-DE or fr-FR see $ instead of euro sign. Cosmetic only; actual charge is correct.',
    submitter='i18n-team'
)
ticket4 = engine.triage(report4)
print("=== TEST 4: Cosmetic Bug ===")
print(f"Category: {ticket4.category}")
print(f"Severity: {ticket4.severity}")
print(f"Priority: {ticket4.priority}")
print(f"Team: {ticket4.assigned_team}")

print("\n[SUCCESS] All tests executed successfully!")
