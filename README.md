# Sortax

Sortax is a completed, full-stack conversational system for preparing Australian
individual tax-return records. It guides users through a structured intake,
retrieves supporting material from a reviewed Australian Taxation Office (ATO)
knowledge base, and produces citation-backed document checklists and summaries
for human review.

Sortax does not lodge tax returns or make personalised tax determinations. Its
core safety rule is that tax-related output must be supported by eligible ATO
evidence. When the required evidence or infrastructure is unavailable, the
system fails closed instead of producing an ungrounded answer.

## Background

Preparing an Australian individual tax return often requires taxpayers to identify
which records are relevant, organise information across several expense and income
categories, and verify requirements against Australian Taxation Office guidance.
The source material is authoritative, but it is distributed across many documents
and can be difficult to translate into a clear, case-specific preparation checklist.

General-purpose AI assistants can make this information easier to access, but
tax-related conversations require stronger controls than ordinary question
answering. Unsupported claims, outdated guidance, missing citations, or lost
conversation state can create significant risks for users.

Sortax was created to address this gap. It combines a structured tax-intake
workflow with retrieval from a reviewed ATO knowledge base. Instead of allowing
the language model to answer tax questions from memory, the system retrieves
eligible source material, preserves citation snapshots, and requires tax-related
outputs to remain grounded in that evidence.

The project focuses on tax-return preparation rather than tax advice or
lodgement. Its purpose is to help users understand what information and records
they may need, preserve their progress across sessions, and produce an auditable
summary for human review. When the required evidence is unavailable or a request
falls outside the supported scope, Sortax asks for clarification or declines to
generate an unsupported answer.

## Features

- React single-page application with responsive chat and tax-intake flows
- FastAPI API with JWT authentication and tenant/user isolation
- Intent routing for general chat, tax assistance, ATO document questions, and
  unsupported tax topics
- Versioned, resumable tax-intake questionnaire for the 2025–26 tax year
- Retrieval-augmented generation backed by reviewed ATO documents in Milvus
- Citation-backed document checklists and optional tax-preparation summaries
- PostgreSQL persistence for conversations, messages, workflow state, generation
  records, retrieval records, and immutable citation snapshots
- Server-Sent Events (SSE) for streaming responses and structured workflow events
- Redis-backed cancellation propagation across API instances
- Idempotent conversation, intake, completion, and summary operations
- Deterministic offline providers for repeatable local operation and tests
- OpenAI and Qwen-compatible provider integrations for explicitly configured use

## Architecture

```text
React frontend
    │ HTTP + SSE
    ▼
FastAPI routes and JWT identity
    │
    ▼
ChatCoordinator / TaxWorkflowCoordinator
    ├── IntentClassifier
    ├── Retrieval planner and Milvus retriever
    ├── Prompt builder and LLM provider
    ├── Unit of Work and repositories
    └── Redis cancellation store
         │
         ├── PostgreSQL: conversations, messages, workflow and audit records
         ├── Milvus: ATO document chunks and metadata
         └── Redis: cancellation signals and service coordination
```

The backend is organised by responsibility under `src/sortax`: `chat` handles
conversation orchestration, `intent` classifies requests, `rag` plans and runs
retrieval, `knowledge` imports the reviewed ATO corpus, `prompting` constructs
grounded prompts, `tax_intake` implements the questionnaire state machine, and
`infrastructure` provides PostgreSQL, Milvus, and Redis adapters.

The API contract and data-handling rules are documented in:

- `docs/openapi.yaml` — machine-readable OpenAPI 3.1 contract
- `docs/data-classification.md` — classification, redaction, retention, and
  deployment controls
- `manifests/ato/sources.yaml` — maintainer-reviewed ATO source catalogue

## Requirements

- Python 3.12 or newer
- Node.js 22.12 or newer
- Docker with Docker Compose
- Reviewed ATO source files listed in `manifests/ato/sources.yaml`

## Local setup

Create the environment file and replace the placeholder JWT and PostgreSQL
secrets:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

PowerShell activation is optional. The virtual-environment interpreter can be
called directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Start PostgreSQL, Redis, etcd, MinIO, and Milvus:

```powershell
docker compose up -d postgres redis etcd minio milvus
docker compose ps
```

Apply the database schema, validate and import the reviewed ATO corpus, and
start the API:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m sortax.knowledge.ingest --manifest manifests/ato/sources.yaml --dry-run
.\.venv\Scripts\python.exe -m sortax.knowledge.ingest --manifest manifests/ato/sources.yaml
.\.venv\Scripts\python.exe -m uvicorn sortax.main:app --reload
```

The API is available at `http://127.0.0.1:8000`, and its interactive OpenAPI
documentation is available at `http://127.0.0.1:8000/docs`.

Install and start the frontend in a second terminal:

```powershell
cd frontend
npm install
npm run generate:types
npm run dev
```

Vite serves the application at `http://127.0.0.1:5173` and proxies `/api` and
`/health` to FastAPI. Authentication tokens remain in memory; the frontend does
not persist them.

Verify service readiness:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
docker compose ps
```

To run the API and Celery worker in containers as well, use:

```powershell
docker compose up --build
```

Stop the services without deleting persistent volumes:

```powershell
docker compose down
```

`docker compose down --volumes` also deletes the local database and vector
store. Use it only when a full local reset is intended.

## ATO knowledge base

ATO files are deliberately managed outside Git. Follow
`manifests/ato/README.md`, save the reviewed source files under `data/ato`, and
keep their manifest metadata current.

Validate source files and preview document/chunk counts without contacting an
embedding provider or Milvus:

```powershell
.\.venv\Scripts\python.exe -m sortax.knowledge.ingest --manifest manifests/ato/sources.yaml --dry-run
```

Importing is idempotent; unchanged documents are reported as skipped. A full
collection rebuild is also available:

```powershell
.\.venv\Scripts\python.exe -m sortax.knowledge.ingest --manifest manifests/ato/sources.yaml
.\.venv\Scripts\python.exe -m sortax.knowledge.ingest --manifest manifests/ato/sources.yaml --rebuild
```

The `--rebuild` option deletes the configured Milvus collection before
re-importing it.

The default deterministic embedding configuration is:

```text
SORTAX_EMBEDDING_PROVIDER=fake
SORTAX_EMBEDDING_MODEL=fake-embedding-v1
SORTAX_EMBEDDING_DIMENSIONS=64
SORTAX_MILVUS_URI=http://localhost:19530
SORTAX_MILVUS_COLLECTION=ato_knowledge_demo
```

When using a real embedding provider, configure its model and vector dimension
before importing the corpus. The provider, API key, and data controls must be
selected explicitly.

## Model and retrieval configuration

The default local configuration uses deterministic LLM, classifier, and
embedding implementations. This mode makes no billable model calls and is
suitable for repeatable demonstrations and automated tests. With Milvus enabled,
retrieval still uses the imported ATO chunks; generated fake-mode wording and
citations are visibly identified as synthetic.

Set `SORTAX_MILVUS_ENABLED=false` to run the fully offline chat path without
Milvus.

### OpenAI

```text
SORTAX_LLM_PROVIDER=openai
SORTAX_LLM_MODEL=<approved-responses-api-model>
SORTAX_LLM_API_KEY=<secret>
```

### Qwen

```text
SORTAX_LLM_PROVIDER=qwen
SORTAX_LLM_MODEL=qwen3.7-flash
SORTAX_QWEN_BASE_URL=https://maas.qianwenaiapi.com/compatible-mode/v1
SORTAX_QWEN_API_KEY=<secret>
```

Use a key and base URL from the same Qwen or Alibaba Cloud product and region.
Credentials from different endpoint families are not interchangeable.

The intent classifier can use a separately selected lightweight Qwen model:

```text
SORTAX_INTENT_CLASSIFIER_PROVIDER=qwen
SORTAX_CLASSIFIER_MODEL=<approved-lightweight-qwen-model>
SORTAX_CLASSIFIER_TIMEOUT_SECONDS=10
SORTAX_CLASSIFIER_MAX_OUTPUT_TOKENS=96
```

Classifier provider errors and invalid output fall back to versioned,
deterministic rules. Ambiguous input fails closed rather than being treated as
ordinary chat.

Remote response storage is disabled for provider streaming requests. The system
records provider request IDs and token counts when available, normalises provider
failures, and does not expose raw provider error details to clients.

Streaming defaults to a 30-second first-token timeout, a heartbeat every 15
seconds, and a five-minute total deadline. These values are configurable through
`SORTAX_FIRST_TOKEN_TIMEOUT_SECONDS`, `SORTAX_STREAM_HEARTBEAT_SECONDS`,
`SORTAX_STREAM_MAX_DURATION_SECONDS`, and `SORTAX_CANCELLATION_POLL_SECONDS`.

## Authentication

For local use, create a short-lived token:

```http
POST /api/v1/dev/token
Content-Type: application/json

{
  "user_id": "11111111-1111-4111-8111-111111111111",
  "tenant_id": "22222222-2222-4222-8222-222222222222"
}
```

The `/api/v1/dev/token` route is available only when `SORTAX_APP_ENV` is
`development` or `test`. Staging and production deployments must supply their
trusted identity integration. Use the returned bearer token with
`GET /api/v1/auth/me` to verify the identity context.

All repository reads require both the trusted tenant ID and owner user ID.
Deleting a conversation cascades through its related chat and retrieval records.

## API workflow

Create a conversation:

```http
POST /api/v1/conversations
Authorization: Bearer <access-token>
Content-Type: application/json

{"title":"ATO records"}
```

Start it with an idempotent greeting:

```http
POST /api/v1/conversations/<conversation-id>/start
Authorization: Bearer <access-token>
Content-Type: application/json

{"client_request_id":"33333333-3333-4333-8333-333333333333"}
```

Send a message:

```http
POST /api/v1/conversations/<conversation-id>/messages
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "client_message_id":"44444444-4444-4444-8444-444444444444",
  "content":"What car records are needed for 2025-26?"
}
```

Message and workflow generation endpoints return `text/event-stream`. Reusing
the same client ID and payload replays the persisted result without starting a
second generation. A request that omits a required claim type or tax year returns
a clarification instead of an unsupported tax answer.

### Tax-intake workflow

A message classified as `tax_assistance` creates or restores the versioned
`limited-tax-2025-26-v1` questionnaire. Clients use these authenticated
endpoints to complete the workflow:

- `GET /api/v1/tax-intakes/{id}` restores the questions, answers, and state.
- `PUT /api/v1/tax-intakes/{id}/answers/{question_key}` replaces one validated
  answer using optimistic version control.
- `POST /api/v1/tax-intakes/{id}/complete` performs multi-topic retrieval and
  streams a citation-backed `document_checklist` and `summary_confirmation`.
- `POST /api/v1/tax-intakes/{id}/summary` generates a `tax_summary` when the user
  explicitly requests one.

Every checklist item references at least one citation from the same persisted
message. Summaries reuse the saved questionnaire, checklist, and citation
snapshots instead of silently retrieving newer evidence.

### Example questions

| Question | Behaviour or source document ID |
| --- | --- |
| `Hello` | General chat without retrieval or citations |
| `What car records are needed for 2025-26?` | `ato-car-expenses-toolkit` |
| `What working-from-home records are needed for 2025-26?` | `ato-working-from-home-expenses` |
| `What salary and wages records are needed for 2025-26?` | `ato-recruitment-consultants-income-deductions` |
| `What self-education records are needed for 2025-26?` | `ato-self-education-expenses` or `ato-tr-2024-3-self-education` |
| `What rental property records are needed for 2025-26?` | `ato-rental-property-records` |
| `What bank interest records are needed for 2025-26?` | `ato-bank-accounts-and-income-bonds` |
| `What car records do I need?` | Clarification requesting the tax year |
| `What car records are needed for 2024-25?` | Unsupported year; no grounded checklist |
| `Help with overseas income tax` | Unsupported topic; no factual tax answer or citations |

If Milvus becomes unavailable, readiness returns HTTP 503 and ATO document
requests terminate without an ungrounded checklist. Liveness remains available
for process monitoring.

## Product scope

Sortax supports six reviewed record-preparation topics for the 2025–26 tax year:
work-related car expenses, working-from-home expenses, salary and wages,
self-education expenses, rental-property records, and bank-interest records.

The ATO corpus is maintainer-reviewed and manually refreshed. Sortax does not
accept file uploads, lodge returns, replace a registered tax agent, or provide a
personalised tax determination. Generated content is intended for human review.
Operational deployments are responsible for their identity provider, secrets,
provider approvals, capacity planning, backups, monitoring, and high-availability
requirements.

## Tests and quality checks

Run the backend checks:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
```

Run the frontend checks:

```powershell
cd frontend
npm run check
npm run test:e2e
```

Live provider and Milvus smoke tests are opt-in because they require local
infrastructure or can make billable network calls:

```powershell
$env:SORTAX_RUN_OPENAI_SMOKE="1"
.\.venv\Scripts\python.exe -m pytest tests/llm_gateway/test_openai_live.py

$env:SORTAX_RUN_QWEN_SMOKE="1"
.\.venv\Scripts\python.exe -m pytest tests/llm_gateway/test_qwen_live.py

$env:SORTAX_RUN_LIVE_INTENT_TESTS="1"
.\.venv\Scripts\python.exe -m pytest tests/intent/test_llm_classifier_live.py

$env:SORTAX_RUN_MILVUS_SMOKE="1"
.\.venv\Scripts\python.exe -m pytest tests/rag/test_phase4b_live.py
```

Install the repository hooks with:

```powershell
.\.venv\Scripts\python.exe -m pre_commit install --hook-type pre-commit --hook-type pre-push
```
