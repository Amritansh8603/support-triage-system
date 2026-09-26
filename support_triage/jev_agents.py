"""Jev (TypeSafe AI) integration.

Jev is a "System One" model: you send it `state` plus typed `questions`
(Choice / Score / Noul) and it returns calibrated probabilities in one
fast, parallel call, instead of generating prose. That maps directly onto
three of our DAG's nodes -- classify, sentiment, escalate -- which are all
judgments, not text generation. draft_reply still needs a real generative
model (or the mock template); Jev cannot write a reply for you.

Enabled by setting TYPESAFE_API_KEY (e.g. in a .env file at the project
root). If the key is absent, `USE_JEV` is False and agents.py falls back
to the rule-based mock functions in llm_mock.py automatically -- no
behavior change if you never touch this file.

If a Jev call itself fails once enabled (bad key, network error, timeout),
it simply raises. It does NOT swallow the error -- the DAG's existing
fallback + circuit breaker in dag.py takes over exactly as it does for a
failing mock node, since orchestrator.py wires the same llm_mock-based
fallbacks regardless of which implementation classify/sentiment/escalate
are using.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()  # picks up a .env file in the project root, if present
except ImportError:
    pass  # python-dotenv is optional; you can also export the var directly

USE_JEV = bool(os.environ.get("TYPESAFE_API_KEY"))

_client: Optional[Any] = None


def get_client():
    """Lazily create a single shared AsyncTypeSafeClient for the process."""
    global _client
    if _client is None:
        from typesafe_sdk import AsyncTypeSafeClient
        _client = AsyncTypeSafeClient()  # reads TYPESAFE_API_KEY from the environment
    return _client


async def close_client() -> None:
    """Call once at shutdown (see cli.py) to release the HTTP client cleanly."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def classify_via_jev(ticket_text: str) -> Dict[str, Any]:
    from typesafe_sdk import Choice

    client = get_client()
    response = await client.system_one(
        state={"ticket": ticket_text},
        questions={
            "category": Choice(
                instructions="What category does this support ticket belong to?",
                criteria={
                    "billing": "Charges, refunds, invoices, subscriptions.",
                    "technical": "Bugs, crashes, login, sync, or 2FA problems.",
                    "account": "Profile, email, or account-access changes.",
                    "shipping": "Order tracking, delivery, shipping address.",
                    "security": "Vulnerabilities, breaches, unauthorized access.",
                    "legal": "Legal threats, lawsuits, subpoenas, GDPR requests.",
                    "general": "Anything that doesn't clearly fit the above.",
                },
            ),
            "priority": Choice(
                instructions="How urgently does this ticket need a human response?",
                criteria={
                    "high": "Time-sensitive, high-stakes, or emotionally intense.",
                    "medium": "A real issue, but not urgent.",
                    "low": "General question, no urgency.",
                },
            ),
        },
    )
    category_answer = response.answers["category"]
    priority_answer = response.answers["priority"]
    return {
        "category": category_answer.choice,
        "confidence": round(category_answer.confidence, 2),
        "priority": priority_answer.choice,
    }


async def sentiment_via_jev(ticket_text: str) -> Dict[str, Any]:
    from typesafe_sdk import Noul

    client = get_client()
    response = await client.system_one(
        state={"ticket": ticket_text},
        questions={
            "very_negative": Noul(instructions="Does this ticket express strong anger or extreme frustration?"),
            "negative": Noul(instructions="Does this ticket express any dissatisfaction or frustration at all?"),
        },
    )
    very_neg = response.answers["very_negative"].noul
    neg = response.answers["negative"].noul
    if very_neg >= 0.6:
        label = "very_negative"
    elif neg >= 0.5:
        label = "negative"
    else:
        label = "neutral"
    return {"sentiment": label, "score": round(neg, 2)}


async def escalate_via_jev(ticket_text: str, category: str, priority: str, sentiment: str) -> Dict[str, Any]:
    from typesafe_sdk import Noul

    client = get_client()
    response = await client.system_one(
        state={
            "ticket": ticket_text,
            "predicted_category": category,
            "predicted_priority": priority,
            "predicted_sentiment": sentiment,
        },
        questions={
            "should_escalate": Noul(
                instructions=(
                    "Given the ticket and the predicted category/priority/sentiment, "
                    "should this be handed to a human instead of auto-resolved?"
                )
            ),
        },
    )
    p = response.answers["should_escalate"].noul
    should_escalate = p >= 0.5

    if category == "security":
        team = "security_response"
    elif category == "legal":
        team = "legal"
    elif should_escalate:
        team = "senior_support"
    else:
        team = None

    return {
        "escalate": should_escalate,
        "team": team,
        "reason": f"Jev escalation probability {p:.2f}",
    }
