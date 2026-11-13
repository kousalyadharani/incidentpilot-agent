# IncidentPilot

IncidentPilot is a portfolio prototype of a human-supervised AI agent for software incident triage. It inspects a bundled synthetic incident, retrieves relevant passages from local runbooks, uses a small allowlisted set of diagnostic tools, explains its evidence, and asks for approval before it simulates a remediation.

This is a reconstructed, original implementation for a portfolio project. It is not connected to Nokia, a real customer environment, or any production service.

## Run it

Requirements: Python 3.10 or newer. No third-party packages are required.

```sh
python3 app.py
```

Open <http://127.0.0.1:8000>. The default offline demonstration runs without an API key and uses BM25 retrieval over the bundled runbooks. To use live dense retrieval and model tool-calling, set `OPENAI_API_KEY` and optionally `OPENAI_MODEL` in the server environment, restart the app, and select **Live model** in the interface. On first live retrieval, the app embeds the runbook chunks with `text-embedding-3-small`, stores vectors in a local SQLite cache, and ranks passages with cosine similarity plus BM25. The model may use those passages as context and cite their source IDs. Live mode sends the incident text and retrieval query to the configured OpenAI API. Do not submit credentials, personal data, customer data, or confidential logs.

## Agent capabilities

- Reads one of three bundled, synthetic incident scenarios.
- Calls bounded tools for service health, structured log analysis, and runbook retrieval.
- Chunks local Markdown runbooks, embeds them on demand, and retrieves source passages with a hybrid vector/BM25 ranker.
- Produces a conclusion with evidence, uncertainty, and a safe next step.
- Can only propose a remediation from a fixed allowlist.
- Requires a human click before the simulator records an approved action.
- Shows an auditable trace of tool calls and approval state.

The demo tools are deterministic and isolated. “Approve” records a simulated action only; it does not restart a real service, roll back a deployment, or access a network.

## Design and safety

- Python standard library server; binds to `127.0.0.1` by default.
- No shell, file-system, network-probing, or arbitrary code-execution tools are exposed to the model.
- Request sizes and tool-call counts are bounded; model tool names and arguments are validated server-side.
- The API key is read only from the server environment and is never returned to the browser.
- The offline agent is rule-based and uses BM25 retrieval; it is explicitly labeled and should not be described as an LLM-generated result.

## Resume framing

**IncidentPilot | Human-supervised incident triage agent** — Built a local-first incident-response prototype with hybrid RAG (dense embeddings + BM25), cited runbook retrieval, bounded diagnostic tools, an auditable tool trace, and approval-gated simulated remediation. Added an offline BM25 mode and optional Responses API integration so the workflow remains demonstrable without credentials.

Do not claim production deployment, measured business impact, or incident-resolution accuracy without conducting and documenting those evaluations.

## Structure

```text
incidentpilot-agent/
├── app.py                 # HTTP API and local server
├── agent.py               # Offline planner and optional model tool loop
├── tools.py               # Synthetic environment and allowlisted tools
├── rag.py                 # Markdown ingestion and hybrid local retrieval
├── knowledge/             # Cited synthetic runbook corpus
├── rag_eval.py            # Retrieval evaluation fixture
├── static/index.html      # Single-page dashboard
└── README.md
```

## API

- `GET /api/status` reports the active mode availability.
- `GET /api/scenarios` returns the synthetic cases.
- `POST /api/run` runs the selected scenario in offline or live mode.
- `POST /api/index` builds or refreshes the local dense vector index; it requires an API key.
- `POST /api/approve` records approval for a pending simulated action.

## Retrieval evaluation

Run `python3 rag_eval.py` for Recall@3 and mean reciprocal rank on the bundled fictional queries using BM25. With `OPENAI_API_KEY` set, run `python3 rag_eval.py --dense` for hybrid embedding and BM25 retrieval. The small fixture evaluates retrieval behavior only; it is not evidence of production incident accuracy.

## Product boundaries

IncidentPilot is a demonstration, not an operational SRE tool. Scenario data is fictional. A model can make mistakes; recommendations require human review. Remediation is simulated, and the tool trace is not a substitute for production observability, change controls, or incident command.
