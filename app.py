"""Streamlit UI for the multi-agent support triage system.

Run locally:
    pip install streamlit
    streamlit run app.py

Deploy for free (public URL, no server to manage):
    1. Push this repo to GitHub (include app.py at the repo root, the
       support_triage/ package, and requirements.txt).
    2. Go to https://share.streamlit.io, sign in with GitHub, "New app".
    3. Pick the repo/branch, set "Main file path" to app.py.
    4. Under "Advanced settings" -> Secrets, add (TOML format, root-level
       keys become environment variables automatically):
           GROQ_API_KEY = "gsk_..."
       (optionally also TYPESAFE_API_KEY = "..." for the Jev integration)
    5. Deploy. You get a public https://<something>.streamlit.app URL.
"""
from __future__ import annotations

import asyncio

import streamlit as st

from support_triage import groq_agents, jev_agents
from support_triage.dag import NodeResult
from support_triage.knowledge_base_data import ARTICLES
from support_triage.orchestrator import TriageOrchestrator

st.set_page_config(page_title="Support Ticket Triage", page_icon="🎫", layout="centered")

EXAMPLES = [
    "I was charged twice for my subscription this month, please refund the extra charge.",
    "The app keeps crashing every time I open it, this is SO frustrating and unacceptable!!!",
    "I think I found a security vulnerability that exposes other users' data.",
    "My package tracking hasn't updated in 8 days, where is my order?",
    "Cancel my account immediately or I will be contacting my lawyer about this.",
    "Quick question - how do I change the email on my account?",
]

STATUS_ICON = {
    "success": "🟢", "fallback": "🟡", "failed": "🔴",
    "skipped": "⚪", "circuit_open": "🟣", "deadline_exceeded": "🟠",
}


@st.cache_resource
def get_orchestrator() -> TriageOrchestrator:
    # Shared across reruns/users on this server process: keeps the KB
    # vector store built once and the circuit breaker's state persistent,
    # exactly like a real long-running service would.
    return TriageOrchestrator()


def run_triage(ticket_text: str):
    orchestrator = get_orchestrator()
    events: list[tuple[str, NodeResult]] = []

    def on_event(event_type, res: NodeResult) -> None:
        events.append((event_type, res))

    async def _go():
        return await orchestrator.triage(ticket_text, on_event=on_event)

    result = asyncio.run(_go())
    return result, events


def mode_label() -> str:
    if groq_agents.USE_GROQ:
        return "Groq (openai/gpt-oss-20b / openai/gpt-oss-120b)"
    if jev_agents.USE_JEV:
        return "Jev (TypeSafe AI)"
    return "mock (rule-based, no API key set)"


st.title("🎫 Multi-Agent Support Triage")
st.caption(f"classify / sentiment / escalate / draft-reply running on: **{mode_label()}**")

with st.sidebar:
    st.subheader("Try an example")
    for ex in EXAMPLES:
        label = ex[:42] + ("…" if len(ex) > 42 else "")
        if st.button(label, key=ex, use_container_width=True):
            st.session_state["ticket_text"] = ex

    st.divider()
    st.subheader("Knowledge base")
    with st.expander(f"{len(ARTICLES)} articles"):
        for art in ARTICLES:
            st.markdown(f"**{art['id']}** · _{art['category']}_ — {art['title']}")

    st.divider()
    st.caption(
        "Fault injection: add `[[FAIL:node_id]]` to a ticket to force that "
        "node to fail on this run — node_id is one of classify, sentiment, "
        "search_kb, draft_reply, escalate, decide."
    )

ticket_text = st.text_area(
    "Paste a support ticket",
    value=st.session_state.get("ticket_text", ""),
    height=120,
    placeholder="e.g. My package tracking hasn't updated in 8 days, where is my order?",
    key="ticket_input",
)

run_clicked = st.button("Triage ticket", type="primary")

if run_clicked:
    if not ticket_text.strip():
        st.warning("Type a ticket first.")
    else:
        with st.spinner("Running the DAG..."):
            result, events = run_triage(ticket_text)

        classify = result.node_results.get("classify")
        sentiment = result.node_results.get("sentiment")
        escalate = result.node_results.get("escalate")
        draft = result.node_results.get("draft_reply")
        decide = result.node_results.get("decide")

        st.subheader("Result")
        c1, c2, c3, c4 = st.columns(4)
        if classify and classify.result:
            c1.metric("Category", classify.result.get("category", "?"))
            c2.metric("Priority", classify.result.get("priority", "?"))
        if sentiment and sentiment.result:
            c3.metric("Sentiment", sentiment.result.get("sentiment", "?"))
        if decide and decide.result:
            c4.metric("Final action", decide.result.get("final_action", "?"))

        st.caption(f"route: `{result.route}` — {result.plan_reason}")

        if escalate and escalate.result and escalate.result.get("escalate"):
            st.warning(f"**Escalated** to `{escalate.result.get('team')}` — {escalate.result.get('reason')}")

        if draft and draft.result:
            st.markdown("**Drafted reply:**")
            st.info(draft.result.get("reply", ""))
            if not draft.result.get("grounded"):
                st.caption("⚠️ not grounded in a confident KB match")

        with st.expander("DAG execution trace", expanded=True):
            for event_type, res in events:
                if event_type != "node_end":
                    continue
                icon = STATUS_ICON.get(res.status.value, "⚫")
                err = f"  — {res.error}" if res.error else ""
                st.text(f"{icon}  {res.node_id:<12} {res.status.value:<18} {res.duration:.3f}s{err}")
            st.caption(f"total wall-clock time: {result.total_duration:.3f}s")

        with st.expander("Circuit breaker state"):
            snap = result.circuit_snapshot
            if not snap:
                st.caption("no failures recorded yet")
            else:
                st.json(snap)
