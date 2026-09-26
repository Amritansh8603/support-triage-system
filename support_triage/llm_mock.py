"""A mock LLM.

Every function here has the shape a real LLM call would have (take text,
return structured output) so swapping in a real Claude/OpenAI call later is
a matter of replacing the function body, not the surrounding orchestration.
"""
from __future__ import annotations

import re
from typing import Dict, List

CATEGORY_KEYWORDS = {
    "billing": ["charge", "charged", "refund", "invoice", "payment", "subscription",
                "billing", "price", "cancel my", "double charge", "overcharged"],
    "technical": ["crash", "bug", "error", "not working", "sync", "login", "log in",
                  "password", "2fa", "authentication", "broken", "freeze", "freezing"],
    "account": ["account", "email address", "locked", "profile", "username", "delete my account"],
    "shipping": ["shipment", "shipping", "delivery", "package", "tracking", "order", "address"],
    "security": ["vulnerability", "breach", "hacked", "exploit", "data leak", "security issue",
                 "unauthorized access", "compromised"],
    "legal": ["lawsuit", "lawyer", "legal action", "sue", "subpoena", "gdpr request", "cease and desist"],
}

URGENT_KEYWORDS = [
    "immediately", "asap", "urgent", "right now", "emergency",
    "furious", "unacceptable", "cancel my account", "lawsuit", "lawyer",
    "breach", "hacked", "compromised", "sue",
]

NEGATIVE_WORDS = ["angry", "furious", "frustrated", "terrible", "awful", "unacceptable",
                   "disappointed", "worst", "horrible", "ridiculous", "scam"]
POSITIVE_WORDS = ["thanks", "thank you", "great", "love", "appreciate", "awesome"]


def _score_keywords(text: str, keywords: List[str]) -> float:
    text_l = text.lower()
    hits = sum(1 for kw in keywords if kw in text_l)
    return hits


def classify(ticket_text: str) -> Dict:
    """Stand-in for an LLM classification call.

    Returns category, confidence, and a heuristic priority.
    """
    scores = {cat: _score_keywords(ticket_text, kws) for cat, kws in CATEGORY_KEYWORDS.items()}
    best_cat = max(scores, key=scores.get)
    best_score = scores[best_cat]

    if best_score == 0:
        category, confidence = "general", 0.35
    else:
        total = sum(scores.values()) or 1
        confidence = min(0.95, 0.4 + 0.6 * (best_score / total))
        category = best_cat

    urgent_hits = _score_keywords(ticket_text, URGENT_KEYWORDS)
    if category in ("security", "legal") or urgent_hits >= 2:
        priority = "high"
    elif urgent_hits == 1 or category == "billing":
        priority = "medium"
    else:
        priority = "low"

    return {"category": category, "confidence": round(confidence, 2), "priority": priority}


def sentiment(ticket_text: str) -> Dict:
    """Stand-in for an LLM sentiment-analysis call."""
    text_l = ticket_text.lower()
    neg = _score_keywords(text_l, NEGATIVE_WORDS)
    pos = _score_keywords(text_l, POSITIVE_WORDS)
    exclaim = ticket_text.count("!")
    caps_ratio = sum(1 for c in ticket_text if c.isupper()) / max(1, len(ticket_text))

    raw = pos - (neg * 1.5) - (exclaim * 0.3) - (caps_ratio * 5)
    if raw <= -1.5:
        label = "very_negative"
    elif raw < 0:
        label = "negative"
    elif raw == 0:
        label = "neutral"
    else:
        label = "positive"
    return {"sentiment": label, "score": round(raw, 2)}


def plan_ticket(ticket_text: str) -> Dict:
    """The planner agent.

    Does a *cheap* pre-scan (not the real classify() call, which runs later
    inside the DAG) to decide the shape of the sub-task graph for this
    ticket: a fast-track graph for legal/security-flavoured tickets that
    skips knowledge-base search and reply drafting and escalates straight
    away, or the standard graph otherwise.
    """
    text_l = ticket_text.lower()
    security_or_legal = any(
        kw in text_l for kw in CATEGORY_KEYWORDS["security"] + CATEGORY_KEYWORDS["legal"]
    )
    if security_or_legal:
        return {
            "route": "fast_track_escalation",
            "nodes": ["classify", "sentiment", "escalate", "decide"],
            "reason": "Ticket text matches security/legal trigger terms; "
                      "skipping KB search and reply drafting to minimize time-to-escalation.",
        }
    return {
        "route": "standard",
        "nodes": ["classify", "sentiment", "search_kb", "draft_reply", "escalate", "decide"],
        "reason": "No high-severity trigger terms found; running the full triage pipeline.",
    }


_TEMPLATES = {
    "billing": "I can see this is a billing question. {kb_snippet}",
    "technical": "Sorry for the trouble — let's get this fixed. {kb_snippet}",
    "account": "Thanks for flagging this account issue. {kb_snippet}",
    "shipping": "Let's track down your order. {kb_snippet}",
    "general": "Thanks for reaching out. {kb_snippet}",
    "security": "Thanks for the report — routing this to our security team. {kb_snippet}",
    "legal": "This has been routed to the appropriate team for review. {kb_snippet}",
}


def draft_reply(category: str, kb_hits: List[Dict]) -> Dict:
    """Stand-in for an LLM drafting call, grounded in retrieved KB snippets."""
    template = _TEMPLATES.get(category, _TEMPLATES["general"])
    if kb_hits:
        top = kb_hits[0]
        snippet = f"Based on '{top['title']}': {top['content']}"
    else:
        snippet = "I wasn't able to find a matching help article, so a specialist will follow up shortly."
    body = template.format(kb_snippet=snippet)
    grounded = bool(kb_hits) and kb_hits[0]["score"] > 0.15
    return {"reply": body, "grounded": grounded, "sources": [h["id"] for h in kb_hits]}
