# RecallOps

RecallOps is a hackathon starter for an event-driven product-recall workflow spanning three simulated business functions:

1. **Product Safety** — interprets recalls, freezes listings, quarantines affected lots, and identifies customers.
2. **Supply Continuity** — predicts stockouts, evaluates replacement suppliers, and creates purchase orders.
3. **Financial Recovery** — calculates recall losses, holds supplier invoices, and creates recovery claims.

The repository provides both a credential-free deterministic enterprise simulation and a deployed cloud path using Google ADK, Gemini, Pub/Sub, Firestore, Cloud Run, Agent Registry, and authenticated A2A handoffs.

## Quick start

Requires Python 3.11 or newer.

```bash
python scripts/generate_seed.py
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000> and run the recall scenario.

Run tests:

```bash
python -m unittest discover -s tests -v
```

Docker:

```bash
docker compose up --build
```

## Current state

Working now:

- Deterministic organization and transaction generator
- Inventory, order, supplier, contract, invoice, and offer datasets
- Replayable inventory and recall events
- Recall containment across listings, lots, and customer orders
- Replacement-supplier selection and simulated purchase orders
- Recall-loss calculation, invoice holds, and supplier claims
- Duplicate-event protection and late-arriving recalled stock handling
- Control-room dashboard with a company/data map, bounded event simulator, human-readable
  agent/A2A actions, and live business-state views
- Typed, department-scoped ADK tools backed by deterministic policy operations
- Per-tool idempotency records and fixed agent identity attribution
- Firestore-backed state using the same contract as the credential-free local store
- Pub/Sub event publishing and authenticated, idempotent push consumption
- A2A 0.3 Agent Cards and JSON-RPC `message/send` endpoints for all three roles
- Official Google ADK A2A execution in cloud mode; deterministic A2A remains available locally
- Cold-start Agent Registry discovery and caching for Supply and Finance A2A agents
- Deterministic, Registry-resolved specialist handoffs driven by validated containment results
- Structured audit events and OpenTelemetry spans for workflows, tools, handoffs, and models
- Optional direct Cloud Trace export and an enforced four-call workflow model budget
- Six deterministic evaluation cases under `evals/`, enforced by the unit suite
- Reproducible, cost-guarded Google Cloud setup and three-service deployment scripts

Verified cloud deployment (2026-08-16):

- Live submission dashboard: https://recallops-recall-sd6ai3qbla-uc.a.run.app
- Gemini 3.5 Flash-Lite routed a synthetic Pub/Sub event through Google ADK
- Registry-resolved private A2A calls invoked the Supply and Finance ADK specialists
- Typed deterministic tools produced 400 quarantined units, one PO, and a $1,475.24 claim
- Cloud Trace export and attributable audit identities were verified for all three agents
- Duplicate delivery was acknowledged without a second mutation or audit record
- Three private, scale-to-zero Cloud Run services share one image
- Recall, Supply, and Finance are discoverable through global Agent Registry A2A cards
- Optional public guided demo limited to four ordered synthetic events, with expiring run
  tokens and a daily run cap; raw mutations, A2A, Pub/Sub, and private state remain protected

Next delivery phase:

- Record the guided control-room demo and prepare the Devpost submission assets

## Lean target architecture

```text
Recall or inventory event
        |
        v
Google Pub/Sub
        |
        v
Recall Coordinator (Google ADK + Gemini)
        |
        +-- Agent Registry --> Supply Continuity Agent
        |
        +-- Agent Registry --> Financial Recovery Agent
        |
        v
Enterprise simulator APIs --> Firestore --> Dashboard
```

## Repository map

```text
app/                 API, workflow engine, state store, and ADK definitions
agent_cards/         A2A Agent Card templates for Agent Registry
docs/                Architecture and data-source decisions
scenarios/           Replayable JSONL enterprise event streams
scripts/             Data generation, public-data ingestion, and cloud helpers
seed/                Generated deterministic enterprise state
tests/               Business workflow and referential-integrity tests
```

## Cost rules

- Cloud Run request-based billing, minimum instances `0`, maximum instances `1`
- Firestore default database only
- One Pub/Sub topic with filtered subscriptions
- Gemini 3.5 Flash-Lite for normal extraction and routing
- Gemini 3.5 Flash only for ambiguous decisions
- No vector database, GKE, Cloud SQL, Redis, or always-on VM
- Maximum four model calls per recall workflow
- One notification template with deterministic mail merge; never one model call per customer

## Data and privacy

All customers, suppliers, contracts, invoices, lots, and claims are synthetic. Public records are used only to ground product and recall characteristics. Synthetic email addresses use the reserved `.invalid` domain.

See [docs/DATA_PLAN.md](docs/DATA_PLAN.md) for sources, licences, and transformation rules.

## Licence

MIT. External datasets remain subject to their own terms; source attribution is documented separately.
