"""Groq integration.

Groq's free tier runs open models (Llama 3.x, etc.) at very high speed via
an OpenAI-compatible chat-completions API. Unlike Jev, Groq is a normal
generative model, so it can back ALL four of the LLM-shaped nodes:
classify, sentiment, and escalate (asked to return structured JSON) as
well as draft_reply (real generated prose, grounded in the KB snippets we
pass it), replacing both jev_agents.py's structured decisions and
llm_mock.py's rule-based logic and templates.

Enabled by setting GROQ_API_KEY (e.g. in a .env file at the project root;
get a free key at https://console.groq.com/keys). If unset, USE_GROQ is
False and agents.py falls back to Jev (if configured) or the rule-based
mock, with no other changes needed.

If a Groq call fails (bad key, network error, malformed JSON back from the
model, timeout), it raises rather than swallowing the error -- the DAG's
existing fallback + circuit breaker in dag.py takes over exactly as it
does for a failing mock or Jev node.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()  # picks up a .env file in the project root, if present
except ImportError:
    pass  # python-dotenv is optional; you can also export the var directly

USE_GROQ = bool(os.environ.get("GROQ_API_KEY"))

# Cheap/fast model for the three structured-judgment nodes; a larger model
# for draft_reply, where prose quality actually matters. (Groq retired
# llama-3.1-8b-instant / llama-3.3-70b-versatile on 2026-08-16; these are
# their official recommended replacements -- see console.groq.com/docs/deprecations.)
FAST_MODEL = "openai/gpt-oss-20b"
QUALITY_MODEL = "openai/gpt-oss-120b"

_client: Optional[Any] = None


def get_client():
    global _client
    if _client is None:
        from groq import AsyncGroq
        _client = AsyncGroq()  # reads GROQ_API_KEY from the environment
    return _client


async def close_client() -> None:
    """Call once at shutdown (see cli.py / app.py) to release the HTTP client."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def _json_completion(system_prompt: str, user_prompt: str,
                             model: str = FAST_MODEL, temperature: float = 0.0) -> Dict[str, Any]:
    client = get_client()
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=temperature,
        max_completion_tokens=300,
    )
    content = response.choices[0].message.content
    return json.loads(content)  # a malformed response raises -> triggers the node's fallback


_CLASSIFY_SYSTEM = (
    "You are a support-ticket classifier. Read the ticket and respond with ONLY a JSON object "
    "with exactly these keys: \"category\" (one of billing, technical, account, shipping, "
    "security, legal, general), \"confidence\" (a float 0-1), \"priority\" (one of high, medium, "
    "low). No other text, no markdown fences."
)


async def classify_via_groq(ticket_text: str) -> Dict[str, Any]:
    result = await _json_completion(_CLASSIFY_SYSTEM, ticket_text)
    return {
        "category": str(result["category"]).strip().lower(),
        "confidence": round(float(result["confidence"]), 2),
        "priority": str(result["priority"]).strip().lower(),
    }


_SENTIMENT_SYSTEM = (
    "You are a sentiment classifier for support tickets. Respond with ONLY a JSON object with "
    "exactly these keys: \"sentiment\" (one of very_negative, negative, neutral, positive), "
    "\"score\" (a float, roughly -2 for very negative up to 1 for positive). No other text."
)


async def sentiment_via_groq(ticket_text: str) -> Dict[str, Any]:
    result = await _json_completion(_SENTIMENT_SYSTEM, ticket_text)
    return {
        "sentiment": str(result["sentiment"]).strip().lower(),
        "score": round(float(result["score"]), 2),
    }


_ESCALATE_SYSTEM = (
    "You decide whether a support ticket needs a human instead of being auto-resolved. Respond "
    "with ONLY a JSON object with exactly these keys: \"escalate\" (true or false), \"team\" "
    "(one of security_response, legal, senior_support, general_support, or null), \"reason\" "
    "(a short string explaining why). No other text."
)


async def escalate_via_groq(ticket_text: str, category: str, priority: str, sentiment: str) -> Dict[str, Any]:
    user_prompt = (
        f"Ticket: {ticket_text}\n"
        f"Predicted category: {category}\nPredicted priority: {priority}\nPredicted sentiment: {sentiment}"
    )
    result = await _json_completion(_ESCALATE_SYSTEM, user_prompt)
    team = result.get("team")
    if team in (None, "null", "None", ""):
        team = None
    return {
        "escalate": bool(result["escalate"]),
        "team": team,
        "reason": str(result.get("reason", "")).strip() or "no reason given",
    }


_DRAFT_SYSTEM = (
    "You write short, warm, professional customer-support replies. If knowledge-base snippets "
    "are provided, ground your reply in them and do not invent policy details that aren't in "
    "them; if none are relevant, say a specialist will follow up. Keep the reply to 2-4 "
    "sentences. Respond with ONLY a JSON object with exactly these keys: \"reply\" (the reply "
    "text), \"grounded\" (true if the reply relies on a provided snippet, else false). No other text."
)


async def draft_reply_via_groq(category: str, kb_hits: List[Dict]) -> Dict[str, Any]:
    if kb_hits:
        kb_text = "\n".join(f"- {h['title']}: {h['content']}" for h in kb_hits)
    else:
        kb_text = "(no relevant knowledge-base article found)"
    user_prompt = f"Ticket category: {category}\nKnowledge base snippets:\n{kb_text}"
    result = await _json_completion(_DRAFT_SYSTEM, user_prompt, model=QUALITY_MODEL, temperature=0.4)
    return {
        "reply": str(result["reply"]).strip(),
        "grounded": bool(result.get("grounded", bool(kb_hits))),
        "sources": [h["id"] for h in kb_hits],
    }
