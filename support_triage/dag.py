"""Hand-rolled DAG task scheduler.

- Kahn's algorithm validates the graph is acyclic and gives a topological
  order (used for validation and for a readable execution plan printout).
- Actual execution is event-driven, not level-by-level: each node waits
  only on its own declared dependencies via asyncio.Event, so independent
  branches genuinely run concurrently rather than in synchronized batches.
- Each node has its own timeout; the whole run has an overall deadline.
- Each node may declare a fallback, invoked on exception, timeout, or an
  open circuit breaker, so a single failing sub-task degrades gracefully
  instead of failing the whole ticket.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FALLBACK = "fallback"
    FAILED = "failed"
    SKIPPED = "skipped"
    CIRCUIT_OPEN = "circuit_open"
    DEADLINE_EXCEEDED = "deadline_exceeded"


class CycleError(Exception):
    pass


@dataclass
class Node:
    id: str
    deps: List[str]
    func: Callable[[Dict[str, Any]], Awaitable[Any]]
    fallback: Optional[Callable[[Dict[str, Any], Optional[Exception]], Awaitable[Any]]] = None
    timeout: float = 1.0
    optional: bool = False  # if True, failure with no fallback doesn't poison downstream


@dataclass
class NodeResult:
    node_id: str
    status: NodeStatus
    result: Any = None
    error: Optional[str] = None
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def duration(self) -> float:
        return max(0.0, self.finished_at - self.started_at)


class CircuitBreaker:
    """Per-node-id circuit breaker.

    Opens after `fail_threshold` consecutive failures for a given node id;
    while open, calls short-circuit straight to the fallback without
    invoking the (presumably struggling) underlying function. After
    `reset_after` seconds it half-opens: the next call is allowed through
    as a trial, and success closes the breaker again.
    """

    def __init__(self, fail_threshold: int = 3, reset_after: float = 20.0):
        self.fail_threshold = fail_threshold
        self.reset_after = reset_after
        self._failures: Dict[str, int] = {}
        self._opened_at: Dict[str, float] = {}

    def is_open(self, node_id: str) -> bool:
        opened_at = self._opened_at.get(node_id)
        if opened_at is None:
            return False
        if time.monotonic() - opened_at >= self.reset_after:
            # half-open: allow exactly one trial through
            self._opened_at.pop(node_id, None)
            return False
        return True

    def record_success(self, node_id: str) -> None:
        self._failures[node_id] = 0
        self._opened_at.pop(node_id, None)

    def record_failure(self, node_id: str) -> None:
        count = self._failures.get(node_id, 0) + 1
        self._failures[node_id] = count
        if count >= self.fail_threshold:
            self._opened_at[node_id] = time.monotonic()

    def failure_count(self, node_id: str) -> int:
        return self._failures.get(node_id, 0)

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        return {
            node_id: {
                "consecutive_failures": self._failures.get(node_id, 0),
                "open": self.is_open(node_id),
            }
            for node_id in set(self._failures) | set(self._opened_at)
        }


def kahn_topological_order(nodes: List[Node]) -> List[str]:
    """Validate the graph is acyclic and return a topological order.

    Classic Kahn's algorithm: repeatedly remove nodes with in-degree 0.
    """
    node_ids = [n.id for n in nodes]
    id_set = set(node_ids)
    in_degree: Dict[str, int] = {nid: 0 for nid in node_ids}
    adjacency: Dict[str, List[str]] = {nid: [] for nid in node_ids}

    for node in nodes:
        for dep in node.deps:
            if dep not in id_set:
                raise ValueError(f"Node '{node.id}' depends on unknown node '{dep}'")
            adjacency[dep].append(node.id)
            in_degree[node.id] += 1

    queue = [nid for nid in node_ids if in_degree[nid] == 0]
    order: List[str] = []
    while queue:
        # Stable order for readability; doesn't affect correctness.
        queue.sort()
        current = queue.pop(0)
        order.append(current)
        for neighbor in adjacency[current]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(order) != len(node_ids):
        remaining = id_set - set(order)
        raise CycleError(f"Cycle detected among nodes: {sorted(remaining)}")
    return order


class DagExecutor:
    def __init__(self, circuit_breaker: Optional[CircuitBreaker] = None,
                 on_event: Optional[Callable[[str, NodeResult], None]] = None):
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.on_event = on_event  # callback(event_type, NodeResult) for live tracing

    async def run(self, nodes: List[Node], context: Dict[str, Any],
                   deadline: float = 5.0) -> Dict[str, NodeResult]:
        """Execute the DAG concurrently, respecting an overall deadline.

        `context` is a shared dict; each node's result is written into
        context[node.id] as soon as it completes, so downstream nodes can
        read upstream results after awaiting the relevant events.
        """
        # Validate topology up front (raises CycleError on a bad graph).
        order = kahn_topological_order(nodes)
        nodes_by_id = {n.id: n for n in nodes}

        events: Dict[str, asyncio.Event] = {nid: asyncio.Event() for nid in nodes_by_id}
        results: Dict[str, NodeResult] = {}

        async def run_node(node: Node) -> None:
            # Wait for all declared dependencies to finish (success, fallback, or failure —
            # a downstream node always gets a *chance* to run; it just may see missing data).
            if node.deps:
                await asyncio.gather(*(events[d].wait() for d in node.deps))

            res = NodeResult(node_id=node.id, status=NodeStatus.RUNNING, started_at=time.monotonic())
            self._emit("node_start", res)

            if self.circuit_breaker.is_open(node.id):
                res.status = NodeStatus.CIRCUIT_OPEN
                if node.fallback is not None:
                    try:
                        res.result = await node.fallback(context, None)
                        res.status = NodeStatus.FALLBACK
                    except Exception as exc:  # fallback itself failed
                        res.status = NodeStatus.FAILED
                        res.error = f"circuit open; fallback also failed: {exc}"
                res.finished_at = time.monotonic()
                context[node.id] = res.result
                results[node.id] = res
                self._emit("node_end", res)
                events[node.id].set()
                return

            try:
                res.result = await asyncio.wait_for(node.func(context), timeout=node.timeout)
                res.status = NodeStatus.SUCCESS
                self.circuit_breaker.record_success(node.id)
            except asyncio.TimeoutError as exc:
                self.circuit_breaker.record_failure(node.id)
                res.error = f"timed out after {node.timeout}s"
                await self._apply_fallback(node, context, res, exc)
            except Exception as exc:  # noqa: BLE001 - deliberately broad: any sub-task can misbehave
                self.circuit_breaker.record_failure(node.id)
                res.error = str(exc)
                await self._apply_fallback(node, context, res, exc)

            res.finished_at = time.monotonic()
            context[node.id] = res.result
            results[node.id] = res
            self._emit("node_end", res)
            events[node.id].set()

        tasks = [asyncio.create_task(run_node(nodes_by_id[nid])) for nid in order]

        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=deadline)
        except asyncio.TimeoutError:
            now = time.monotonic()
            for nid, task in zip(order, tasks):
                if nid not in results:
                    task.cancel()
                    results[nid] = NodeResult(
                        node_id=nid, status=NodeStatus.DEADLINE_EXCEEDED,
                        error=f"overall deadline of {deadline}s exceeded",
                        started_at=now, finished_at=now,
                    )
                    events[nid].set()
                    self._emit("node_end", results[nid])

        return results

    async def _apply_fallback(self, node: Node, context: Dict[str, Any],
                                res: NodeResult, exc: Exception) -> None:
        if node.fallback is not None:
            try:
                res.result = await node.fallback(context, exc)
                res.status = NodeStatus.FALLBACK
            except Exception as fb_exc:
                res.status = NodeStatus.FAILED
                res.error = f"{res.error}; fallback also failed: {fb_exc}"
        else:
            res.status = NodeStatus.SKIPPED if node.optional else NodeStatus.FAILED

    def _emit(self, event_type: str, res: NodeResult) -> None:
        if self.on_event is not None:
            self.on_event(event_type, res)
