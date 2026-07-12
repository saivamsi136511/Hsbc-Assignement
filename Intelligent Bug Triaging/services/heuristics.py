"""
services/heuristics.py
=======================
Keyword-based heuristic scoring for bug categorization, urgency detection,
and severity classification.

This module provides the offline, zero-dependency fallback for the triaging
engine.  It uses regex pattern matching against curated keyword dictionaries
to produce category, urgency, and severity scores without any LLM call.

The heuristic approach is intentionally simple and transparent:
- Every scoring decision is driven by explicit keyword lists.
- Scores are additive — more matching signals → higher confidence.
- It always produces a result, so triage never blocks on LLM availability.

Public API
----------
score_category(text)                  -> str
score_urgency(text)                   -> (int, str)
score_severity(text, urgency_level)   -> str
heuristic_triage(report)              -> dict
"""

import re
from typing import Any, Dict, List, Tuple

from domain.constants import CATEGORIES, SEVERITY_PRIORITY, TEAM_MAP


# ---------------------------------------------------------------------------
# Keyword dictionaries
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: Dict[str, List[Tuple[str, int]]] = {
    "UI": [
        (r"\b(ui|ux|button|dropdown|modal|tooltip|checkbox|radio|form|layout|css|style|design|font|icon|image|render|display|screen|visual|color|colour|theme|responsive|animation|menu|nav|sidebar|header|footer|table|grid|card|badge|spinner|loading|skeleton|dark.?mode|light.?mode|widget|component|page|view|front.?end|html|dom)\b", 3),
        (r"\b(click|tap|scroll|swipe|hover|focus|blur|resize|zoom|drag|drop)\b", 2),
        (r"\b(misalign|overlap|truncat|overflow|cut.?off|broken.?layout|not.?visible|hidden|blank|empty.?screen|white.?screen|flash|flicker|glitch)\b", 3),
    ],
    "Backend": [
        (r"\b(api|endpoint|server|service|backend|request|response|http|rest|graphql|grpc|webhook|microservice|route|controller|handler|middleware|gateway|proxy|timeout|latency|throughput|queue|worker|job|task|cron|scheduler)\b", 3),
        (r"\b(500|502|503|504|400|401|403|404|429)\b", 3),
        (r"\b(null.?pointer|npe|stack.?overflow|out.?of.?memory|heap|exception|error|crash|panic|traceback|segfault)\b", 2),
        (r"\b(slow|hang|freeze|stuck|unresponsive|not.?responding|loop|deadlock|race.?condition)\b", 2),
    ],
    "Database": [
        (r"\b(database|db|sql|nosql|mysql|postgres|postgresql|sqlite|mongodb|redis|cassandra|dynamodb|oracle|mssql|query|migration|schema|table|column|index|transaction|rollback|commit|constraint|foreign.?key|primary.?key|deadlock|lock|connection.?pool)\b", 3),
        (r"\b(insert|update|delete|select|join|group.?by|order.?by|where|having|limit|offset)\b", 2),
        (r"\b(duplicate.?key|unique.?constraint|not.?null|data.?corruption|data.?loss|inconsistent|stale|sync|replication)\b", 3),
    ],
    "Authentication": [
        (r"\b(login|logout|sign.?in|sign.?out|auth|authentication|authorization|permission|role|access|privilege|credential|password|username|token|jwt|oauth|sso|2fa|mfa|session|cookie|csrf|cors)\b", 3),
        (r"\b(forbidden|unauthorized|403|401|locked.?out|account.?locked|invalid.?password|wrong.?password|expired.?token|refresh.?token)\b", 3),
        (r"\b(register|signup|sign.?up|forgot.?password|reset.?password|verify|verification)\b", 2),
    ],
    "Security": [
        (r"\b(security|vulnerability|exploit|attack|breach|hack|injection|xss|csrf|sql.?injection|xxe|ssrf|idor|rce|privilege.?escalation|data.?exposure|leak|sensitive|pii|gdpr|compliance)\b", 4),
        (r"\b(malicious|suspicious|threat|risk|audit|pentest|scan|firewall|rate.?limit|brute.?force)\b", 3),
    ],
    "Performance": [
        (r"\b(slow|performance|latency|throughput|response.?time|load.?time|page.?speed|ttfb|lcp|cls|fid|bottleneck|profil|benchmark|memory.?leak|cpu|ram|resource|cache|cdn|optimize)\b", 3),
        (r"\b(timeout|hang|freeze|unresponsive|lag|spike|degraded|degradation)\b", 2),
        (r"\b(high.?load|traffic|scale|concurren|thread|process|async|parallel)\b", 2),
    ],
    "Network": [
        (r"\b(network|connectivity|connection|dns|ip|tcp|udp|ssl|tls|https|certificate|firewall|vpn|proxy|bandwidth|packet|latency|ping|socket|websocket)\b", 3),
        (r"\b(unreachable|offline|down|disconnect|timeout|refused|reset|connection.?error)\b", 2),
    ],
    "Mobile": [
        (r"\b(mobile|ios|android|app|iphone|ipad|tablet|phone|native|react.?native|flutter|swift|kotlin|apk|ipa|push.?notification|background.?task|battery|gps|camera|microphone|bluetooth)\b", 3),
        (r"\b(crash|freeze|slow|laggy|unresponsive).{0,30}(app|mobile|phone)\b", 2),
    ],
    "Infrastructure": [
        (r"\b(infrastructure|infra|devops|ci|cd|pipeline|deploy|deployment|kubernetes|k8s|docker|container|pod|helm|terraform|ansible|aws|gcp|azure|cloud|vm|instance|server|host|cluster|node|ingress|loadbalancer|autoscaling)\b", 3),
        (r"\b(build|compile|test|lint|scan|artifact|release|rollback|canary|blue.?green)\b", 2),
    ],
}

_URGENCY_KEYWORDS: List[Tuple[str, int]] = [
    (r"\b(production|prod|live)\b", 20),
    (r"\b(all users|every user|everyone|all customers)\b", 20),
    (r"\b(outage|down|offline|unavailable|not working)\b", 18),
    (r"\b(data loss|data corruption|lost data)\b", 20),
    (r"\b(urgent|urgently|asap|immediately|emergency|critical)\b", 15),
    (r"\b(payment|billing|checkout|revenue|money|transaction|financial)\b", 15),
    (r"\b(security breach|hack|exploit|vulnerability)\b", 18),
    (r"\b(cannot login|can't login|unable to login|locked out)\b", 15),
    (r"\b(crashing|crashed|crash loop|keeps crashing)\b", 12),
    (r"\b(thousands|millions|hundreds).{0,30}(users|customers|requests)\b", 15),
    (r"\b(sla|slo|breach|violation)\b", 12),
    (r"\b(escalat|exec|ceo|cto|vp|manager)\b", 10),
    (r"\b(workaround|no fix|stuck|blocked)\b", 8),
    (r"\b(high priority|high-priority|p1|p0)\b", 15),
    (r"\b(intermittent|sometimes|occasionally|rare)\b", -8),
    (r"\b(minor|cosmetic|typo|small|enhancement|nice to have|low priority)\b", -10),
]

_SEVERITY_KEYWORDS: Dict[str, List[str]] = {
    "Critical": [
        r"\b(production down|all users affected|complete outage|data loss|security breach|payment failure|site down|service down)\b",
        r"\b(cannot.{0,10}(login|access|use)|system.{0,10}(down|unavailable|broken))\b",
        r"\b(production outage|prod.{0,5}outage|production.{0,15}(down|unavailable|broken))\b",
        r"\b(100%.{0,15}(users|customers)|every.{0,10}user|all.{0,10}(users|customers).{0,10}(affected|impacted|locked))\b",
        r"\b(immediate.{0,10}fix|needs immediate|critical security|critical vulnerability|locked out)\b",
        r"\b(payment.{0,15}(broken|failed|failing|failure)|checkout.{0,10}(broken|down|failing))\b",
    ],
    "High": [
        r"\b(http 500|500 error|server error|500 internal|application error|null ?pointer|npe|nullpointerexception|exception|crash)\b",
        r"\b(cannot.{0,15}(complete|submit|save|load)|broken.{0,10}(feature|functionality|flow))\b",
        r"\b(many users|multiple users|significant|major|serious|large.{0,10}(number|portion))\b",
        r"\b(authentication.{0,15}(fail|broken|down)|login.{0,15}(fail|broken|not working))\b",
    ],
    "Medium": [
        r"\b(sometimes|intermittent|occasional|some users|few users|workaround available)\b",
        r"\b(slow|delay|timeout|degraded|performance issue)\b",
        r"\b(approximately [0-9]+%.{0,10}users|subset of users|certain users)\b",
    ],
    "Low": [
        r"\b(minor|cosmetic|typo|spelling|alignment|color|colour|small|enhancement|request|suggestion|nice.?to.?have|localization|formatting)\b",
    ],
}


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def score_category(text: str) -> str:
    """
    Assign a bug category using keyword pattern matching.

    Each category has a list of regex patterns, each with a weight.  The
    category whose patterns accumulate the highest weighted match count wins.

    Args:
        text: Combined bug title + description text (lowercased internally).

    Returns:
        The category name with the highest score (e.g. ``"Backend"``), or
        ``"Unknown"`` if no category pattern matched at all.
    """
    text_lower = text.lower()
    scores: Dict[str, int] = {cat: 0 for cat in CATEGORIES if cat != "Unknown"}

    for category, patterns in _CATEGORY_KEYWORDS.items():
        for pattern, weight in patterns:
            matches = re.findall(pattern, text_lower)
            scores[category] += len(matches) * weight

    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "Unknown"


def score_urgency(text: str) -> Tuple[int, str]:
    """
    Compute a 0–100 urgency score and a human-readable urgency level.

    Positive keywords (e.g. "production down", "all users") add to the score;
    negative keywords (e.g. "minor", "typo") subtract from it.  The raw total
    is clamped to [0, 100].

    Args:
        text: Combined bug title + description text (lowercased internally).

    Returns:
        A tuple ``(urgency_score, urgency_level)`` where:
        - ``urgency_score`` is an integer in ``[0, 100]``.
        - ``urgency_level`` is one of ``"Critical"``, ``"High"``,
          ``"Medium"``, or ``"Low"``.
    """
    text_lower = text.lower()
    raw = 0

    for pattern, weight in _URGENCY_KEYWORDS:
        if re.search(pattern, text_lower):
            raw += weight

    score = max(0, min(100, raw))
    if score >= 70:
        level = "Critical"
    elif score >= 45:
        level = "High"
    elif score >= 20:
        level = "Medium"
    else:
        level = "Low"

    return score, level


def score_severity(text: str, urgency_level: str) -> str:
    """
    Assign a severity level using keyword pattern matching.

    Checks severity keywords from most to least severe and returns the first
    match.  Falls back to mapping the urgency level to an equivalent severity
    if no specific severity keyword is found.

    Args:
        text:          Combined bug title + description text (lowercased internally).
        urgency_level: Urgency level from ``score_urgency`` used as a fallback.

    Returns:
        One of ``"Critical"``, ``"High"``, ``"Medium"``, or ``"Low"``.
    """
    text_lower = text.lower()
    for severity in ("Critical", "High", "Medium", "Low"):
        for pattern in _SEVERITY_KEYWORDS[severity]:
            if re.search(pattern, text_lower):
                return severity
    return urgency_level if urgency_level in ("Critical", "High", "Medium", "Low") else "Medium"


def heuristic_triage(report) -> Dict[str, Any]:
    """
    Produce a complete triage result using heuristics only (no LLM required).

    Runs ``score_category``, ``score_urgency``, and ``score_severity`` in
    sequence to build a full triage result dict.  Confidence is estimated
    from the number of matching category signals.

    This function is always called first; the LLM result (if available)
    is then merged on top of it in the ``TriagingEngine``.

    Args:
        report: A ``BugReport`` instance with ``title`` and ``description`` fields.

    Returns:
        A dict with keys: ``category``, ``severity``, ``priority``,
        ``assigned_team``, ``confidence``, ``urgency_score``,
        ``urgency_level``, ``summary``, ``suggested_fix``,
        ``analysis_source``.
    """
    from domain.constants import BASE_CONFIDENCE, CONFIDENCE_PER_SIGNAL, UNKNOWN_CONFIDENCE

    combined = f"{report.title} {report.description}"
    category = score_category(combined)
    urgency_score, urgency_level = score_urgency(combined)
    severity = score_severity(combined, urgency_level)
    priority = SEVERITY_PRIORITY.get(severity, "P3")
    assigned_team = TEAM_MAP.get(category, "Triage Team")

    text_lower = combined.lower()
    signal_count = sum(
        1 for pattern, _ in _CATEGORY_KEYWORDS.get(category, [])
        if re.search(pattern, text_lower)
    )
    confidence = min(90, BASE_CONFIDENCE + signal_count * CONFIDENCE_PER_SIGNAL) if category != "Unknown" else UNKNOWN_CONFIDENCE

    return {
        "category":        category,
        "severity":        severity,
        "priority":        priority,
        "assigned_team":   assigned_team,
        "confidence":      confidence,
        "urgency_score":   urgency_score,
        "urgency_level":   urgency_level,
        "summary":         f"Bug report: {report.title.strip().rstrip('.')}.",
        "suggested_fix":   "Investigate the issue based on the description. Check relevant logs and reproduce in a staging environment.",
        "analysis_source": "heuristic",
    }
