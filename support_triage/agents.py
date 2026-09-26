"""Agent implementations: the actual work behind each DAG node.

Each node function takes the shared `context` dict and returns a result;
each fallback takes (context, exception) and returns a safe degraded
result. A tiny fault-injection hook lets you force any node to fail by
including `[[FAIL:node_id]]` in the ticket text, e.g. `[[FAIL:search_kb]]`
— handy for demoing fallbacks and the circuit breaker interactively.
"""
from __future__ import annotations

import asyncio
import random
import re
from typing import Any, Dict, Optional

from . import groq_agents, jev_agents, llm_mock
from .vector_store import VectorStore

_FAIL_RE = re.compile(r"\[\[FAIL:([a-zA-Z_]+)\]\]")


def _maybe_inject_failure(context: Dict[str, Any], node_id: str) -> None:
    ticket_text = context.get("ticket_text", "")
    forced = set(_FAIL_RE.findall(ticket_text))
    if node_id in forced:
        raise RuntimeError(f"injected failure for demo purposes on node '{node_id}'")


async def _simulated_latency(lo: float = 0.05, hi: float = 0.25) -> None:
    await asyncio.sleep(random.uniform(lo, hi))


# ---------------------------------------------------------------- classify
async def classify_node(context: Dict[str, Any]) -> Dict:
    _maybe_inject_failure(context, "classify")
    if groq_agents.USE_GROQ:
        return await groq_agents.classify_via_groq(context["ticket_text"])
    if jev_agents.USE_JEV:
        return await jev_agents.classify_via_jev(context["ticket_text"])
    await _simulated_latency()
    return llm_mock.classify(context["ticket_text"])


async def classify_fallback(context: Dict[str, Any], exc: Optional[Exception]) -> Dict:
    return {"category": "general", "confidence": 0.0, "priority": "medium", "degraded": True}


# ---------------------------------------------------------------- sentiment
async def sentiment_node(context: Dict[str, Any]) -> Dict:
    _maybe_inject_failure(context, "sentiment")
    if groq_agents.USE_GROQ:
        return await groq_agents.sentiment_via_groq(context["ticket_text"])
    if jev_agents.USE_JEV:
        return await jev_agents.sentiment_via_jev(context["ticket_text"])
    await _simulated_latency()
    return llm_mock.sentiment(context["ticket_text"])


async def sentiment_fallback(context: Dict[str, Any], exc: Optional[Exception]) -> Dict:
    return {"sentiment": "unknown", "score": 0.0, "degraded": True}


# ---------------------------------------------------------------- search_kb
async def search_kb_node(context: Dict[str, Any]) -> list:
    _maybe_inject_failure(context, "search_kb")
    await _simulated_latency(0.1, 0.4)
    store: VectorStore = context["kb_store"]
    hits = store.search(context["ticket_text"], top_k=2)
    return [
        {"id": doc.id, "title": doc.metadata.get("title", ""), "content": doc.text, "score": score}
        for doc, score in hits
    ]


async def search_kb_fallback(context: Dict[str, Any], exc: Optional[Exception]) -> list:
    return [{
        "id": "kb-011",
        "title": "Contacting a human support agent",
        "content": "Knowledge-base search was unavailable; routing to a human agent.",
        "score": 0.0,
    }]


# ---------------------------------------------------------------- draft_reply
async def draft_reply_node(context: Dict[str, Any]) -> Dict:
    _maybe_inject_failure(context, "draft_reply")
    classify_result = context.get("classify") or {}
    kb_hits = context.get("search_kb") or []
    category = classify_result.get("category", "general")
    if groq_agents.USE_GROQ:
        return await groq_agents.draft_reply_via_groq(category, kb_hits)
    await _simulated_latency(0.1, 0.3)
    return llm_mock.draft_reply(category, kb_hits)


async def draft_reply_fallback(context: Dict[str, Any], exc: Optional[Exception]) -> Dict:
    return {
        "reply": "Thanks for reaching out — a member of our team will follow up with you shortly.",
        "grounded": False,
        "sources": [],
        "degraded": True,
    }


# ---------------------------------------------------------------- escalate
async def escalate_node(context: Dict[str, Any]) -> Dict:
    _maybe_inject_failure(context, "escalate")
    classify_result = context.get("classify") or {}
    sentiment_result = context.get("sentiment") or {}
    category = classify_result.get("category", "general")
    priority = classify_result.get("priority", "medium")
    sent = sentiment_result.get("sentiment", "neutral")

    if groq_agents.USE_GROQ:
        return await groq_agents.escalate_via_groq(context["ticket_text"], category, priority, sent)
    if jev_agents.USE_JEV:
        return await jev_agents.escalate_via_jev(context["ticket_text"], category, priority, sent)

    await _simulated_latency(0.05, 0.2)
    should_escalate = (
        priority == "high"
        or sent == "very_negative"
        or category in ("security", "legal")
    )
    if category == "security":
        team = "security_response"
    elif category == "legal":
        team = "legal"
    elif should_escalate:
        team = "senior_support"
    else:
        team = None

    reason_bits = []
    if priority == "high":
        reason_bits.append("high priority")
    if sent == "very_negative":
        reason_bits.append("very negative sentiment")
    if category in ("security", "legal"):
        reason_bits.append(f"category={category}")

    return {
        "escalate": should_escalate,
        "team": team,
        "reason": ", ".join(reason_bits) if reason_bits else "no escalation trigger met",
    }


async def escalate_fallback(context: Dict[str, Any], exc: Optional[Exception]) -> Dict:
    # Fail SAFE: if we can't confidently decide, escalate to a human rather
    # than silently auto-resolving something that might have needed a person.
    return {
        "escalate": True,
        "team": "general_support",
        "reason": "escalation decision failed; failing safe to human review",
        "degraded": True,
    }


# ---------------------------------------------------------------- decide
async def decide_node(context: Dict[str, Any]) -> Dict:
    _maybe_inject_failure(context, "decide")
    await _simulated_latency(0.02, 0.1)
    escalate_result = context.get("escalate") or {}
    draft = context.get("draft_reply")

    if escalate_result.get("escalate"):
        return {
            "final_action": "route_to_human",
            "team": escalate_result.get("team"),
            "reply_sent": False,
        }
    if draft and draft.get("grounded"):
        return {"final_action": "auto_resolve", "team": None, "reply_sent": True}
    return {"final_action": "route_to_human", "team": "general_support", "reply_sent": False}


async def decide_fallback(context: Dict[str, Any], exc: Optional[Exception]) -> Dict:
    return {
        "final_action": "needs_manual_review",
        "team": "general_support",
        "reply_sent": False,
        "degraded": True,
    }
