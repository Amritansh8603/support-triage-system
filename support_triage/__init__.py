"""Multi-agent customer support triage system.

A DAG-based orchestrator: a planner agent breaks an incoming ticket into
sub-tasks (classify, sentiment, search_kb, draft_reply, escalate, decide),
which are scheduled with a hand-rolled Kahn's-algorithm topological
validator and executed concurrently with asyncio, subject to a deadline
budget, per-node fallback paths, and a circuit breaker per node type.
"""
