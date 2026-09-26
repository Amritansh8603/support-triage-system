"""Ties the planner, DAG executor, and agents together for one ticket."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import agents, llm_mock
from .dag import CircuitBreaker, DagExecutor, Node, NodeResult
from .vector_store import VectorStore, build_default_kb

# Per-node timeout budgets (seconds). A real system would tune these against
# p99 latency of each underlying service.
# Real network calls (Groq/Jev) need more room than the near-instant mock.
# draft_reply gets the most headroom since it's actual text generation on
# a larger model, not just a short structured judgment.
NODE_TIMEOUTS = {
    "classify": 1.5,
    "sentiment": 1.5,
    "search_kb": 0.6,
    "draft_reply": 2.5,
    "escalate": 1.5,
    "decide": 0.3,
}

NODE_REGISTRY = {
    "classify": (agents.classify_node, agents.classify_fallback, []),
    "sentiment": (agents.sentiment_node, agents.sentiment_fallback, []),
    "search_kb": (agents.search_kb_node, agents.search_kb_fallback, ["classify"]),
    "draft_reply": (agents.draft_reply_node, agents.draft_reply_fallback, ["classify", "search_kb"]),
    # escalate depends on classify+sentiment in every route; when search_kb/draft_reply
    # are skipped (fast-track route) it simply runs earlier, in parallel with nothing else.
    "escalate": (agents.escalate_node, agents.escalate_fallback, ["classify", "sentiment"]),
}


def _decide_deps(included_nodes: List[str]) -> List[str]:
    deps = ["escalate"]
    if "draft_reply" in included_nodes:
        deps.append("draft_reply")
    return deps


@dataclass
class TicketResult:
    ticket_id: str
    ticket_text: str
    route: str
    plan_reason: str
    node_results: Dict[str, NodeResult]
    total_duration: float
    circuit_snapshot: Dict[str, Any] = field(default_factory=dict)

    @property
    def final_action(self) -> Optional[str]:
        decide = self.node_results.get("decide")
        if decide and decide.result:
            return decide.result.get("final_action")
        return None


class TriageOrchestrator:
    def __init__(self, kb_store: Optional[VectorStore] = None,
                 circuit_breaker: Optional[CircuitBreaker] = None,
                 deadline: float = 8.0):
        self.kb_store = kb_store or build_default_kb()
        self.circuit_breaker = circuit_breaker or CircuitBreaker(fail_threshold=3, reset_after=15.0)
        self.deadline = deadline

    def build_nodes(self, included_node_ids: List[str]) -> List[Node]:
        nodes: List[Node] = []
        for nid in included_node_ids:
            func, fallback, deps = NODE_REGISTRY[nid]
            nodes.append(Node(id=nid, deps=deps, func=func, fallback=fallback,
                               timeout=NODE_TIMEOUTS[nid]))
        nodes.append(Node(
            id="decide", deps=_decide_deps(included_node_ids),
            func=agents.decide_node, fallback=agents.decide_fallback,
            timeout=NODE_TIMEOUTS["decide"],
        ))
        return nodes

    async def triage(self, ticket_text: str, on_event=None) -> TicketResult:
        ticket_id = str(uuid.uuid4())[:8]
        plan = llm_mock.plan_ticket(ticket_text)
        included = [n for n in plan["nodes"] if n != "decide"]  # decide is added by build_nodes

        nodes = self.build_nodes(included)
        context: Dict[str, Any] = {"ticket_text": ticket_text, "kb_store": self.kb_store}

        executor = DagExecutor(circuit_breaker=self.circuit_breaker, on_event=on_event)
        start = time.monotonic()
        results = await executor.run(nodes, context, deadline=self.deadline)
        total_duration = time.monotonic() - start

        return TicketResult(
            ticket_id=ticket_id,
            ticket_text=ticket_text,
            route=plan["route"],
            plan_reason=plan["reason"],
            node_results=results,
            total_duration=total_duration,
            circuit_snapshot=self.circuit_breaker.snapshot(),
        )
