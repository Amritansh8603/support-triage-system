# Multi-Agent Customer Support Triage System

A DAG-based orchestrator for support tickets. A planner decides the sub-task graph for each ticket, independent sub-tasks run concurrently under `asyncio`, the whole run is bounded by a deadline, and every step has a fallback path and a circuit breaker.

It runs fully locally with a built-in rule-based mock, so no API keys are needed. Optionally, plug in Groq (free tier) or Jev (TypeSafe AI) for real LLM calls.

## Features

- **Planner agent** picks a `standard` graph or a `fast_track_escalation` graph (skips KB search and drafting for security/legal tickets).
- **Concurrent DAG execution** using Kahn's algorithm. `classify` and `sentiment` run in parallel, as do `search_kb` and `escalate`.
- **Deadline budget** (default 3s) for the whole run, plus per-node timeouts.
- **Fallbacks and circuit breaker.** A failing node falls back to a safe default, and repeated failures open its breaker. Escalation fails *safe* by escalating.
- **Vector-store knowledge base** using dependency-free hashed bag-of-words embeddings and cosine similarity.
- **Pluggable LLM backend** with priority Groq > Jev > mock.
- **Two interfaces:** an interactive CLI and a Streamlit web UI with a live execution trace.
- **Fault injection:** add `[[FAIL:node_id]]` to a ticket to force a node to fail.

## Project Structure

```
support_triage_project/
├── app.py                      # Streamlit web UI
├── requirements.txt
├── .env                        # API keys (not committed)
└── support_triage/
    ├── dag.py                  # Generic scheduler: Kahn's algorithm, async executor, circuit breaker
    ├── orchestrator.py         # Builds the per-ticket DAG from the planner's output and runs it
    ├── agents.py               # DAG node functions and their fallbacks
    ├── llm_mock.py             # Rule-based stand-in for LLM calls (classify, sentiment, planner, draft)
    ├── groq_agents.py          # Groq-backed nodes (all four LLM-shaped nodes)
    ├── jev_agents.py           # Jev-backed nodes (classify, sentiment, escalate)
    ├── vector_store.py         # Embeddings + cosine-similarity search
    ├── knowledge_base_data.py  # KB articles
    └── cli.py                  # Interactive CLI
```

## Getting Started

### Prerequisites

- Python 3.9+ (developed on 3.13)

### Installation

```bash
git clone <your-repo-url>
cd support_triage_project
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration (optional)

With no keys set, the mock backend is used. To use a real LLM, create a `.env` file in the project root:

```
GROQ_API_KEY=your_groq_key_here        # free key: https://console.groq.com/keys
TYPESAFE_API_KEY=your_typesafe_key     # optional, used only if no Groq key is set
```

| Key | Backend | Nodes covered |
| --- | --- | --- |
| `GROQ_API_KEY` | Groq (Llama 3.x) | classify, sentiment, escalate, draft_reply |
| `TYPESAFE_API_KEY` | Jev (TypeSafe AI) | classify, sentiment, escalate |
| neither | Built-in mock | all |

If a real call fails (bad key, network error, timeout), the DAG's fallback and circuit breaker handle it like any other node failure.

## Usage

### CLI

```bash
python3 -m support_triage.cli
```

Type a ticket and press Enter. For example:

```
I was charged twice for my subscription this month, please refund the extra charge.
I think I found a security vulnerability that exposes other users' data.
Where is my order? [[FAIL:search_kb]]
```

Send the failing ticket a few times in a row, then run `stats` to watch `search_kb` trip to `OPEN`.

Commands: `help`, `kb`, `stats`, `examples`, `quit`.

### Web UI

```bash
streamlit run app.py
```

Opens at <http://localhost:8501>. It shows the classification, drafted reply, escalation decision, and a per-node execution trace.

To deploy free on Streamlit Community Cloud, push the repo to GitHub (without `.env`), set the main file to `app.py`, and put your keys in the app's Secrets. See [support_triage/README.md](support_triage/README.md) for step-by-step details.

## Going to Production

- Replace `llm_mock.py` with real model calls (same input/output shapes) and `vector_store.py` with a real embedding model plus FAISS, pgvector, or Pinecone. The current hashed embeddings can mis-rank articles on short or ambiguous tickets.
- Tune `NODE_TIMEOUTS` and the overall deadline against real p99 latencies.
- Persist results and move to a queue/worker model for throughput.

## More Documentation

Detailed design notes, a brief-to-code mapping, and provider setup live in [support_triage/README.md](support_triage/README.md).
