"""
triaging_engine.py — AI-powered NLP triaging engine for Intelligent Bug Triaging.

Pipeline:
  1. Urgency / sentiment analysis  -> urgency_score (0-100) + urgency_level
  2. Category classification       -> UI | Backend | Database | Auth | ...
  3. Severity scoring              -> Critical | High | Medium | Low
  4. Priority assignment           -> P1 | P2 | P3 | P4
  5. Team assignment               -> from category
  6. LLM enrichment (optional)     -> summary, suggested_fix, improved category/severity
  7. Confidence scoring

Falls back 100% to heuristics when no LLM is available.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from models import (
    BugReport,
    CATEGORIES,
    SEVERITY_PRIORITY,
    TEAM_MAP,
    Ticket,
)

# ===========================================================================
# 1. KEYWORD DICTIONARIES
# ===========================================================================

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


# ===========================================================================
# 2. HEURISTIC ANALYSIS
# ===========================================================================

def _score_category(text: str) -> str:
    text_lower = text.lower()
    scores: Dict[str, int] = {cat: 0 for cat in CATEGORIES if cat != "Unknown"}

    for category, patterns in _CATEGORY_KEYWORDS.items():
        for pattern, weight in patterns:
            matches = re.findall(pattern, text_lower)
            scores[category] += len(matches) * weight

    best_cat = max(scores, key=lambda k: scores[k])
    return best_cat if scores[best_cat] > 0 else "Unknown"


def _score_urgency(text: str) -> Tuple[int, str]:
    text_lower = text.lower()
    raw_score = 0

    for pattern, weight in _URGENCY_KEYWORDS:
        if re.search(pattern, text_lower):
            raw_score += weight

    score = max(0, min(100, raw_score))

    if score >= 70:
        level = "Critical"
    elif score >= 45:
        level = "High"
    elif score >= 20:
        level = "Medium"
    else:
        level = "Low"

    return score, level


def _score_severity(text: str, urgency_level: str) -> str:
    text_lower = text.lower()

    for severity in ("Critical", "High", "Medium", "Low"):
        for pattern in _SEVERITY_KEYWORDS[severity]:
            if re.search(pattern, text_lower):
                return severity

    return {"Critical": "Critical", "High": "High", "Medium": "Medium", "Low": "Low"}.get(urgency_level, "Medium")


def _heuristic_triage(report: BugReport) -> Dict[str, Any]:
    combined = f"{report.title} {report.description}"

    category      = _score_category(combined)
    urgency_score, urgency_level = _score_urgency(combined)
    severity      = _score_severity(combined, urgency_level)
    priority      = SEVERITY_PRIORITY.get(severity, "P3")
    assigned_team = TEAM_MAP.get(category, "Triage Team")

    text_lower = combined.lower()
    signal_count = 0
    for pattern_weight in _CATEGORY_KEYWORDS.get(category, []):
        pattern = pattern_weight[0]
        if re.search(pattern, text_lower):
            signal_count += 1
    confidence = min(90, 40 + signal_count * 10) if category != "Unknown" else 20

    summary = f"Bug report: {report.title.strip().rstrip('.')}."
    suggested_fix = (
        "Investigate the issue based on the description. "
        "Check relevant logs and reproduce in a staging environment."
    )

    return {
        "category":        category,
        "severity":        severity,
        "priority":        priority,
        "assigned_team":   assigned_team,
        "confidence":      confidence,
        "urgency_score":   urgency_score,
        "urgency_level":   urgency_level,
        "summary":         summary,
        "suggested_fix":   suggested_fix,
        "analysis_source": "heuristic",
    }


# ===========================================================================
# 3. LLM CLIENT
# ===========================================================================

_SYSTEM_PROMPT = """You are an expert software engineering triage assistant.
A user has submitted a bug report. Analyze it and respond with ONLY a single
JSON object — no markdown fences, no prose before or after — with exactly
these keys:

{
  "category": "one of: UI | Backend | Database | Authentication | Security | Performance | Network | Mobile | Infrastructure | Unknown",
  "severity": "one of: Critical | High | Medium | Low",
  "urgency_level": "one of: Critical | High | Medium | Low",
  "urgency_score": <integer 0-100>,
  "summary": "1-2 sentence plain English summary of the bug",
  "suggested_fix": "concrete actionable suggestion to fix or investigate the issue",
  "confidence": <integer 0-100>
}

Rules:
- severity=Critical if production is down, all users are affected, data loss, payment failure, or security breach
- severity=High if a major feature is broken for many users
- severity=Medium if intermittent or affecting some users
- severity=Low if cosmetic / minor / enhancement
- urgency_score reflects time-sensitivity (100 = immediate)
"""


class LLMUnavailable(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1", timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _post(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            f"{self.base_url}{path}", data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 404 or "not found" in body.lower():
                raise LLMUnavailable(f"Model '{self.model}' not found. Run: ollama pull {self.model}") from e
            raise LLMUnavailable(f"Ollama HTTP {e.code}: {body[:200]}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise LLMUnavailable(f"Cannot reach Ollama at {self.base_url}: {e}") from e

    def triage(self, report: BugReport) -> Dict[str, Any]:
        user_msg = f"Bug Report Title: {report.title}\n\nBug Description:\n{report.description}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            "stream": False, "format": "json", "options": {"temperature": 0.1},
        }
        result  = self._post("/api/chat", payload)
        content = result.get("message", {}).get("content", "")
        return _parse_llm_json(content)


class OpenAICompatClient:
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.model    = model
        self.api_key  = api_key
        self.timeout  = timeout

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/models")
            if self.api_key:
                req.add_header("Authorization", f"Bearer {self.api_key}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def triage(self, report: BugReport) -> Dict[str, Any]:
        user_msg = f"Bug Report Title: {report.title}\n\nBug Description:\n{report.description}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=data,
            headers={"Content-Type": "application/json"},
        )
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise LLMUnavailable(f"Cannot reach {self.base_url}: {e}") from e
        content = result["choices"][0]["message"]["content"]
        return _parse_llm_json(content)


def _parse_llm_json(content: str) -> Dict[str, Any]:
    content = content.strip()
    for attempt in (content, re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.MULTILINE)):
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{.*\}", content, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass
    return {}


# ===========================================================================
# 4. TRIAGING ENGINE (public API)
# ===========================================================================

class TriagingEngine:
    def __init__(
        self,
        provider:   str  = "ollama",
        model:      str  = "llama3.1",
        ollama_url: str  = "http://localhost:11434",
        api_base:   Optional[str] = None,
        api_key:    str  = "",
        timeout:    int  = 60,
    ):
        self.provider = provider
        self._client  = self._build_client(provider, model, ollama_url, api_base, api_key, timeout)
        self._llm_available: Optional[bool] = None

    def _build_client(self, provider, model, ollama_url, api_base, api_key, timeout):
        if provider == "none":
            return None
        if provider == "ollama":
            return OllamaClient(base_url=ollama_url, model=model, timeout=timeout)
        if provider == "openai":
            if not api_base:
                raise ValueError("api_base is required for provider=openai")
            return OpenAICompatClient(base_url=api_base, model=model, api_key=api_key, timeout=timeout)
        return None

    def _check_llm(self) -> bool:
        if self._client is None:
            return False
        if self._llm_available is None:
            self._llm_available = self._client.is_available()
        return self._llm_available

    def triage(self, report: BugReport) -> Ticket:
        heuristic = _heuristic_triage(report)
        llm_result: Dict[str, Any] = {}
        analysis_source = "heuristic"

        if self._check_llm():
            try:
                llm_result = self._client.triage(report)  # type: ignore[union-attr]
                if llm_result:
                    model_name = getattr(self._client, "model", "unknown")
                    analysis_source = f"LLM ({model_name})"
            except LLMUnavailable:
                self._llm_available = False
                llm_result = {}

        def _get(key: str, default: Any) -> Any:
            return llm_result.get(key) or heuristic.get(key) or default

        category      = _validate_category(_get("category", "Unknown"))
        severity      = _validate_severity(_get("severity", "Medium"))
        urgency_score = int(_get("urgency_score", heuristic["urgency_score"]))
        urgency_level = _validate_urgency(_get("urgency_level", heuristic["urgency_level"]))
        priority      = SEVERITY_PRIORITY.get(severity, "P3")
        assigned_team = TEAM_MAP.get(category, "Triage Team")
        confidence    = min(100, max(0, int(_get("confidence", heuristic["confidence"]))))
        summary       = _get("summary", heuristic["summary"])
        suggested_fix = _get("suggested_fix", heuristic["suggested_fix"])

        return Ticket(
            title           = report.title,
            description     = report.description,
            submitter       = report.submitter,
            submitted_at    = report.submitted_at or datetime.utcnow().isoformat(),
            category        = category,
            severity        = severity,
            priority        = priority,
            assigned_team   = assigned_team,
            confidence      = confidence,
            urgency_score   = urgency_score,
            urgency_level   = urgency_level,
            summary         = summary,
            suggested_fix   = suggested_fix,
            analysis_source = analysis_source,
            status          = "Open",
        )


def _validate_category(value: str) -> str:
    for c in CATEGORIES:
        if c.lower() == value.lower():
            return c
    for c in CATEGORIES:
        if c.lower() in value.lower():
            return c
    return "Unknown"


def _validate_severity(value: str) -> str:
    for s in ("Critical", "High", "Medium", "Low"):
        if s.lower() == value.lower():
            return s
    return "Medium"


def _validate_urgency(value: str) -> str:
    for u in ("Critical", "High", "Medium", "Low"):
        if u.lower() == value.lower():
            return u
    return "Low"
