"""Interactive CLI for the support triage orchestrator.

Run with:  python -m support_triage.cli
"""
from __future__ import annotations

import asyncio
import time

from . import groq_agents, jev_agents
from .dag import NodeResult
from .knowledge_base_data import ARTICLES
from .orchestrator import TriageOrchestrator

STATUS_ICON = {
    "success": "\u2713",            # check
    "fallback": "\u21ba",           # circular arrow
    "failed": "\u2717",             # cross
    "skipped": "\u2013",            # dash
    "circuit_open": "\u26a1",       # lightning bolt
    "deadline_exceeded": "\u23f1",  # stopwatch
}

BANNER = r"""
+----------------------------------------------------------------+
|  Multi-Agent Customer Support Triage System (mock LLM, local)  |
+----------------------------------------------------------------+
Type a support ticket and press Enter to triage it live.
Commands:
  help              show this message
  kb                list knowledge-base articles
  stats             show circuit breaker state
  examples          print a few example tickets you can paste
  quit / exit       leave

Fault injection: include [[FAIL:node_id]] in a ticket to force that node
to fail on this run, e.g.:
  My card was charged twice, please refund me. [[FAIL:search_kb]]
node_id is one of: classify, sentiment, search_kb, draft_reply, escalate, decide
"""

EXAMPLES = [
    "I was charged twice for my subscription this month, please refund the extra charge.",
    "The app keeps crashing every time I open it, this is SO frustrating and unacceptable!!!",
    "I think I found a security vulnerability that exposes other users' data.",
    "My package tracking hasn't updated in 8 days, where is my order?",
    "Cancel my account immediately or I will be contacting my lawyer about this.",
    "Quick question - how do I change the email on my account?",
]


def _print_banner() -> None:
    print(BANNER)
    if groq_agents.USE_GROQ:
        mode = "Groq (openai/gpt-oss-20b / openai/gpt-oss-120b)"
    elif jev_agents.USE_JEV:
        mode = "Jev (TypeSafe AI)"
    else:
        mode = "mock (rule-based, no API key)"
    print(f"classify / sentiment / escalate / draft_reply are running on: {mode}\n")


def _print_kb() -> None:
    print("\nKnowledge base articles:")
    for art in ARTICLES:
        print(f"  [{art['category']:<9}] {art['id']}  {art['title']}")
    print()


def _print_examples() -> None:
    print("\nExample tickets:")
    for ex in EXAMPLES:
        print(f"  - {ex}")
    print()


def _print_stats(orchestrator: TriageOrchestrator) -> None:
    snap = orchestrator.circuit_breaker.snapshot()
    print("\nCircuit breaker state:")
    if not snap:
        print("  (no failures recorded yet)")
    else:
        for node_id, info in snap.items():
            state = "OPEN" if info["open"] else "closed"
            print(f"  {node_id:<12} consecutive_failures={info['consecutive_failures']:<3} state={state}")
    print()


def _make_event_logger(t0: float):
    def on_event(event_type: str, res: NodeResult) -> None:
        elapsed = time.monotonic() - t0
        if event_type == "node_start":
            print(f"  [{elapsed:6.3f}s] -> {res.node_id:<12} started")
        else:  # node_end
            icon = STATUS_ICON.get(res.status.value, "?")
            extra = f"  ({res.error})" if res.error else ""
            print(f"  [{elapsed:6.3f}s] {icon} {res.node_id:<12} {res.status.value:<18} "
                  f"in {res.duration:5.3f}s{extra}")
    return on_event


def _print_result_summary(result) -> None:
    print(f"\n  route={result.route}   ({result.plan_reason})")
    decide = result.node_results.get("decide")
    escalate = result.node_results.get("escalate")
    draft = result.node_results.get("draft_reply")
    classify = result.node_results.get("classify")

    if classify and classify.result:
        c = classify.result
        print(f"  classified as: category={c.get('category')} "
              f"priority={c.get('priority')} confidence={c.get('confidence')}")

    if decide and decide.result:
        print(f"  FINAL ACTION: {decide.result.get('final_action')}"
              + (f"  -> team: {decide.result.get('team')}" if decide.result.get("team") else ""))

    if escalate and escalate.result and escalate.result.get("escalate"):
        print(f"  escalation reason: {escalate.result.get('reason')}")

    if draft and draft.result:
        print(f"  draft reply (grounded={draft.result.get('grounded')}):")
        print(f"    \"{draft.result.get('reply')}\"")

    print(f"  total wall-clock time: {result.total_duration:.3f}s\n")


async def _run_ticket(orchestrator: TriageOrchestrator, ticket_text: str) -> None:
    t0 = time.monotonic()
    print(f"\nTriaging ticket...")
    result = await orchestrator.triage(ticket_text, on_event=_make_event_logger(t0))
    _print_result_summary(result)


async def main() -> None:
    orchestrator = TriageOrchestrator()
    _print_banner()
    try:
        while True:
            try:
                line = input("ticket> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nbye!")
                return

            if not line:
                continue
            cmd = line.lower()
            if cmd in ("quit", "exit"):
                print("bye!")
                return
            if cmd == "help":
                _print_banner()
                continue
            if cmd == "kb":
                _print_kb()
                continue
            if cmd == "stats":
                _print_stats(orchestrator)
                continue
            if cmd == "examples":
                _print_examples()
                continue

            await _run_ticket(orchestrator, line)
    finally:
        await jev_agents.close_client()  # no-op if Jev was never used
        await groq_agents.close_client()  # no-op if Groq was never used


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
