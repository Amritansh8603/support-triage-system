# Multi-Agent Customer Support Triage System

A DAG-based orchestrator for support tickets: a planner agent decides the
sub-task graph per ticket, independent sub-tasks run concurrently under
asyncio, the whole run is bounded by a deadline budget, and every sub-task
has a fallback path plus a circuit breaker. Runs fully locally — no API
keys, no external services.

## Run it

```bash
cd support_triage/..     # the directory containing the support_triage/ folder
python3 -m support_triage.cli
```

Type a ticket and press Enter. Try:

```
I was charged twice for my subscription this month, please refund the extra charge.
The app keeps crashing every time I open it, this is SO frustrating and unacceptable!!!
I think I found a security vulnerability that exposes other users' data.
```

Force a node to fail to see the fallback path and circuit breaker in action:

```
Where is my order? [[FAIL:search_kb]]
```

Send that a couple more times in a row and `stats` will show `search_kb`
tripping to `OPEN`.

CLI commands: `help`, `kb`, `stats`, `examples`, `quit`.

## How it maps to the brief

| Brief requirement | Where it lives |
|---|---|
| Planner agent breaks ticket into sub-tasks | `llm_mock.plan_ticket()` — picks between a `standard` graph and a `fast_track_escalation` graph (skips KB search / drafting for security/legal tickets) |
| Task graph / Kahn's algorithm scheduler | `dag.kahn_topological_order()` validates the graph is acyclic; `DagExecutor` schedules nodes event-driven so independent branches run truly concurrently |
| Concurrent execution | `classify` + `sentiment` run in parallel as roots; `search_kb` and (once `classify`+`sentiment` land) `escalate` run in parallel; see the live timestamps in the CLI trace |
| Deadline budget | `TriageOrchestrator(deadline=...)` — overall wall-clock cap wrapping the whole DAG run (default 3s); each node also has its own per-node timeout |
| Fallback path if a step fails | Every `Node` has a `fallback` coroutine (`agents.py`) invoked on exception, timeout, or an open circuit — e.g. KB search failure falls back to a generic "contact support" article; escalation failure fails *safe* (escalates) rather than silently auto-resolving |
| Vector store for the knowledge base | `vector_store.py` — dependency-free hashed bag-of-words embeddings + cosine similarity over `knowledge_base_data.py` |
| Circuit breaker | `dag.CircuitBreaker` — opens a node after N consecutive failures, short-circuits straight to fallback while open, half-opens after a cooldown |

## Files

- `dag.py` — the generic, ticket-agnostic scheduler (Kahn's algorithm + async execution + circuit breaker). This is the reusable orchestration core.
- `llm_mock.py` — stand-in for real LLM calls (classify, sentiment, planner, drafting). Swap these for real API calls without touching the scheduler.
- `vector_store.py` / `knowledge_base_data.py` — the KB.
- `agents.py` — glues the mock LLM + vector store into DAG node functions and their fallbacks.
- `orchestrator.py` — builds the per-ticket DAG from the planner's output and runs it.
- `cli.py` — interactive demo.

## Optional: run classify / sentiment / escalate on real Jev calls

[Jev](https://typesafe.ai) (TypeSafe AI) is a "System One" model: instead of
generating text, you send it `state` plus typed questions (`Choice`,
`Score`, `Noul`) and it returns calibrated probabilities in one fast,
parallel call. That's exactly what `classify`, `sentiment`, and `escalate`
need -- structured judgments, not prose -- so `jev_agents.py` swaps those
three nodes onto real Jev calls when a key is present, with zero code
changes needed for `search_kb`, `draft_reply`, or the orchestrator itself.
`draft_reply` keeps using the mock template (or a real generative model),
since Jev can't write a reply for you.

1. Install the extra dependencies:
   ```bash
   pip install typesafe-sdk python-dotenv
   ```
2. Get a key from the [TypeSafe console](https://console.typesafe.ai) (new
   accounts get $5 in free credit).
3. Copy `.env.example` to `.env` in the project root (next to the
   `support_triage/` folder) and fill in your key:
   ```
   TYPESAFE_API_KEY=your_api_key_here
   ```
4. Run the CLI as usual. The banner will now say
   `classify / sentiment / escalate are running on: Jev (TypeSafe AI)`.

No other flags needed -- `jev_agents.USE_JEV` is just `bool(os.environ.get("TYPESAFE_API_KEY"))`,
checked once per node call. Delete or unset the key to fall back to the
free mock instantly.

**Why this integration is low-risk:** if a Jev call fails for any reason
(bad key, network error, timeout, rate limit), it simply raises -- the
DAG's existing fallback and circuit-breaker machinery in `dag.py` catches
it exactly like a failing mock node would, and `orchestrator.py` wires the
same safe rule-based fallbacks (`agents.classify_fallback`, etc.)
regardless of which implementation is behind the node. You get real
structured judgments when Jev is healthy, and the same fail-safe behavior
as before when it isn't -- no new error-handling code required.

## Optional: run classify / sentiment / escalate / draft_reply on Groq (free)

[Groq](https://groq.com) runs open models (Llama 3.x, etc.) at very high
speed on a free tier via an OpenAI-compatible API. Unlike Jev, Groq is a
normal generative model, so `groq_agents.py` can back **all four**
LLM-shaped nodes: `classify` / `sentiment` / `escalate` (asked to return
structured JSON) and `draft_reply` (real generated prose, grounded in the
KB snippets). Priority order in `agents.py` is **Groq > Jev > mock** --
set `GROQ_API_KEY` and it takes over everything; leave it unset and any
configured Jev key is used instead; leave both unset and you get the
free rule-based mock.

1. Install: `pip install groq python-dotenv`
2. Get a free key at [console.groq.com/keys](https://console.groq.com/keys) (no card required).
3. Add to your `.env` (see `.env.example`):
   ```
   GROQ_API_KEY=your_groq_key_here
   ```
4. Run the CLI or the web UI as usual -- the banner/caption will say
   `Groq (llama-3.1-8b-instant / llama-3.3-70b-versatile)`.

Same fail-safe design as Jev: a bad key, network error, malformed JSON,
or timeout just raises, and the DAG's existing fallback + circuit breaker
catches it -- no new error handling needed to add a new provider.

## Deploying a public web UI (free, Streamlit Community Cloud)

`app.py` wraps the same `TriageOrchestrator` in a small Streamlit UI:
paste a ticket, click a button, see the classification, the drafted
reply, the escalation decision, and a live DAG execution trace (with
per-node status/duration and circuit-breaker state) -- no terminal needed.

**Run it locally first:**
```bash
pip install streamlit
streamlit run app.py
```
It opens at `http://localhost:8501`. It uses the same `.env` file as the
CLI, so if you've already set `GROQ_API_KEY`, the web UI picks it up too.

**Deploy it for free, with a public URL:**

1. Push this whole project to a GitHub repo -- `app.py` at the repo root,
   the `support_triage/` folder, and `requirements.txt`. Do **not** commit
   your `.env` file (add it to `.gitignore`); secrets go in step 4 instead.
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with
   GitHub, click **"New app"**.
3. Pick the repo and branch, and set **"Main file path"** to `app.py`.
4. Click **"Advanced settings"** and paste into the **Secrets** box (TOML
   format, root-level keys -- Streamlit Cloud automatically exposes these
   as real OS environment variables, which is exactly what `os.environ.get(...)`
   in `groq_agents.py`/`jev_agents.py` reads):
   ```
   GROQ_API_KEY = "gsk_..."
   ```
5. Click **Deploy**. You'll get a public `https://<something>.streamlit.app`
   URL you can share with anyone -- they get the UI, not your API key.

Since `TriageOrchestrator` is cached with `@st.cache_resource`, the
knowledge-base vector store is built once and the circuit breaker's state
persists across visitors hitting the same deployed instance, the same way
it would in a real backend service.

## Extending toward a real deployment

- Replace `llm_mock.py` functions with real Claude/OpenAI calls (same input/output shapes), and `vector_store.py` with a real embedding model + FAISS/pgvector/Pinecone.
- The hashed bag-of-words embedding is intentionally crude — you'll notice it can mis-rank KB articles on short or ambiguous tickets (e.g. "cancel my subscription and refund me" can pull in an unrelated "sync" article because they share generic words). A real embedding model fixes this; it's a good talking point on why embedding quality matters more than orchestration complexity for retrieval accuracy.
- `NODE_TIMEOUTS` and the overall `deadline` should be tuned against real p99 latencies per dependency.
- Add persistence (e.g. write `TicketResult` to a datastore) and a proper queue/worker model (Celery/Temporal/etc.) for production throughput instead of a single-process CLI loop.
