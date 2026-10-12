# Sortax Chat Backend

The project has completed the Phase 0R contracts, ATO ingestion and Milvus
retrieval path, persistence foundation, and the Phase 5A–5D limited-tax workflow.
The local Phase 6 Demo uses deterministic Fake LLM and Embedding providers by
default; billable real-provider checks remain explicit operator-run steps.

Phase 0 contracts are documented in:

- `docs/openapi.yaml` — machine-readable OpenAPI 3.1 draft
- `docs/data-classification.md` — data classification, redaction, retention, and production gates
- `manifests/ato/sources.yaml` — maintainer-reviewed ATO Demo source catalogue

## Local setup

Requires Python 3.12 or newer.

```powershell
Copy-Item .env.example .env
# Replace the placeholder JWT and PostgreSQL secrets in .env.
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn sortax.main:app --reload
```

If PowerShell script execution is restricted, activation is optional:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn sortax.main:app --reload
```

The API is available at `http://localhost:8000`, with interactive API docs at
`http://localhost:8000/docs`.

Alembic owns the PostgreSQL schema. `alembic upgrade head` creates the
conversation, message, generation run, retrieval run, and immutable citation
snapshot tables. Repository reads always require both the trusted tenant ID and
owner user ID; deleting a conversation physically cascades through its chat and
RAG execution records.

## Local containers

After creating `.env` and replacing its placeholder secrets, start PostgreSQL,
Redis, and Milvus with its required etcd and MinIO services:

```powershell
docker compose up -d postgres redis etcd minio milvus
docker compose ps
```

The first start downloads the pinned container images and can take several
minutes. Apply the schema, import the reviewed ATO files, and run the API from the
existing Python environment:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m sortax.knowledge.ingest --manifest manifests/ato/sources.yaml --dry-run
.\.venv\Scripts\python.exe -m sortax.knowledge.ingest --manifest manifests/ato/sources.yaml
.\.venv\Scripts\python.exe -m uvicorn sortax.main:app --reload
```

The import is idempotent: a second run reports unchanged documents as skipped.
Readiness dynamically checks PostgreSQL, Redis, and Milvus. Verify:

```powershell
Invoke-RestMethod http://localhost:8000/health/ready
docker compose ps
```

To run the API and Celery worker in containers instead, use `docker compose up
--build`. Building those two application images needs several additional GB of
Docker storage and is not required for the local Demo.

Milvus listens on `http://localhost:19530`; its local WebUI is available at
`http://localhost:9091/webui/`. These ports and the bundled MinIO credentials
are for the local Demo only.

Stop the services without deleting their volumes:

```powershell
docker compose down
```

To remove local database and vector data as well, explicitly run
`docker compose down --volumes`. This is destructive and is not required for a
normal stop.

## RAG configuration

The local default uses `FakeEmbeddingProvider`, which is deterministic and makes
no network calls. Its dimension must match the future Milvus collection:

```text
SORTAX_EMBEDDING_PROVIDER=fake
SORTAX_EMBEDDING_MODEL=fake-embedding-v1
SORTAX_EMBEDDING_DIMENSIONS=64
SORTAX_MILVUS_URI=http://localhost:19530
SORTAX_MILVUS_COLLECTION=ato_knowledge_demo
```

The ATO files are intentionally not downloaded by the software. Follow
`manifests/ato/README.md`, manually save the reviewed files under `data/ato`,
and keep their manifest metadata current. Selecting the OpenAI Embedding
Provider is opt-in and requires its API key and data-control review. Configure a
real model such as `text-embedding-3-small` and a matching dimension before
importing.

Validate local files and preview document/chunk counts without contacting an
Embedding Provider or Milvus:

```powershell
python -m sortax.knowledge.ingest --manifest manifests/ato/sources.yaml --dry-run
```

Import files idempotently, or explicitly rebuild the whole Demo collection:

```powershell
python -m sortax.knowledge.ingest --manifest manifests/ato/sources.yaml
python -m sortax.knowledge.ingest --manifest manifests/ato/sources.yaml --rebuild
```

The command prints a JSON summary of ready, imported, unchanged/skipped, failed,
and written chunk counts. `--rebuild` deletes the configured Milvus collection,
so use it only when a full re-import is intended.

Create a development token:

```http
POST /api/v1/dev/token
Content-Type: application/json

{
  "user_id": "11111111-1111-4111-8111-111111111111",
  "tenant_id": "22222222-2222-4222-8222-222222222222"
}
```

The `/api/v1/dev/token` route is mounted only when `SORTAX_APP_ENV` is
`development` or `test`. Production and staging must use a future external
identity provider.

Use the returned bearer token with `GET /api/v1/auth/me` to verify the trusted
identity context.

## Chat retrieval modes

In `test`, the API uses deterministic `FakeRetriever` and `FakeLLMProvider`
implementations. In `development`, an enabled Milvus connection selects the
Phase 4 online retriever while the LLM defaults to fake. The online retriever embeds
only a minimized claim-type/year query, applies claim-type and tax-year filters,
and fails closed when no result meets `SORTAX_RETRIEVAL_SCORE_THRESHOLD`.
Set `SORTAX_MILVUS_ENABLED=false` to retain the all-fake local chat path.

Real LLM use is explicit. Set all three values before starting the API; no real
provider is called merely because an API key happens to exist elsewhere:

```text
SORTAX_LLM_PROVIDER=openai
SORTAX_LLM_MODEL=<approved-responses-api-model>
SORTAX_LLM_API_KEY=<secret>
```

Qwen's OpenAI-compatible Responses API is also supported. Keys created in the
Qwen AI Platform use that platform's displayed pay-as-you-go base URL:

```text
SORTAX_LLM_PROVIDER=qwen
SORTAX_LLM_MODEL=qwen3.7-flash
SORTAX_QWEN_BASE_URL=https://maas.qianwenaiapi.com/compatible-mode/v1
SORTAX_QWEN_API_KEY=<secret>
```

Keep the API key and base URL from the same Qwen or Alibaba Cloud product and
region; credentials from different endpoint families are not interchangeable.

The Phase 5C.1 intent classifier is independently opt-in. It reuses the same
Qwen credential and base URL while keeping a separate, lightweight model ID:

```text
SORTAX_INTENT_CLASSIFIER_PROVIDER=qwen
SORTAX_CLASSIFIER_MODEL=<approved-lightweight-qwen-model>
SORTAX_CLASSIFIER_TIMEOUT_SECONDS=10
SORTAX_CLASSIFIER_MAX_OUTPUT_TOKENS=96
```

It makes a non-streaming structured-output request and maps only to
`general_chat`, `tax_assistance`, `ato_document_requirements`, or
`unsupported_tax_topic`. Provider errors and invalid output are recorded without
user text and explicitly fall back to versioned deterministic rules. Ambiguous
fallback input fails closed instead of being treated as ordinary chat.

The provider streams through the Responses API with remote response storage
disabled. The application records the provider request ID and input/output token
counts when returned, normalizes provider failures, and never returns raw provider
error details to the client. Production and staging fail closed if a real provider
is not configured or injected.

Streaming defaults to a 30-second first-token timeout, a heartbeat every 15
seconds, and a five-minute total deadline. Redis propagates cancellation between
API instances; cancellation during planning or retrieval prevents an LLM request.
These are configurable with `SORTAX_FIRST_TOKEN_TIMEOUT_SECONDS`,
`SORTAX_STREAM_HEARTBEAT_SECONDS`, `SORTAX_STREAM_MAX_DURATION_SECONDS`, and
`SORTAX_CANCELLATION_POLL_SECONDS`.

Create a conversation with the bearer token, then post a message to its message
endpoint:

```http
POST /api/v1/conversations
Authorization: Bearer <development-token>
Content-Type: application/json

{"title":"ATO Demo"}
```

```http
POST /api/v1/conversations/<conversation-id>/messages
Authorization: Bearer <development-token>
Content-Type: application/json

{
  "client_message_id":"33333333-3333-4333-8333-333333333333",
  "content":"What car records are needed for 2025-26?"
}
```

The second request returns `text/event-stream`. Reusing the same
`client_message_id` and content replays the persisted result without another
generation. A question missing its claim type or tax year returns a clarification
instead of a grounded answer.

### Phase 5D limited-tax workflow

Clients may idempotently generate the first assistant greeting with
`POST /api/v1/conversations/{id}/start`. A message classified as
`tax_assistance` creates or restores the versioned `limited-tax-2025-26-v1`
questionnaire and returns it as structured SSE content.

Persist or restore the workflow with these authenticated endpoints:

- `GET /api/v1/tax-intakes/{id}` restores the three questions, answers and state.
- `PUT /api/v1/tax-intakes/{id}/answers/{question_key}` replaces one validated answer.
- `POST /api/v1/tax-intakes/{id}/complete` performs multi-topic retrieval and streams a
  `document_checklist` followed by `summary_confirmation`.
- `POST /api/v1/tax-intakes/{id}/summary` generates a `tax_summary` only when
  `requested=true`; declining is persisted without calling the LLM.

Checklist items must each reference at least one citation ordinal from the same
persisted message. Tax summaries reuse the saved questionnaire, checklist, and
citation snapshots; they do not silently retrieve newer evidence.

Fake-mode evidence and citations are visibly marked as fake and must not be treated
as ATO advice. With Milvus enabled, grounded answers use the imported ATO chunks
and persist citation snapshots. Real-provider checks are opt-in because they make
external, potentially billable requests; they are not required for the repeatable
local Phase 6 Demo.

## Repeatable Phase 6 Demo

Keep `SORTAX_LLM_PROVIDER=fake`, `SORTAX_INTENT_CLASSIFIER_PROVIDER=fake`, and
`SORTAX_EMBEDDING_PROVIDER=fake` for a free, deterministic local run. The Milvus
retrieval and ATO citations are real even though the generated wording is fake.

Create a token and conversation in PowerShell:

```powershell
$tokenResponse = Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/api/v1/dev/token `
  -ContentType application/json `
  -Body '{"user_id":"11111111-1111-4111-8111-111111111111","tenant_id":"22222222-2222-4222-8222-222222222222"}'
$headers = @{ Authorization = "Bearer $($tokenResponse.access_token)" }
$conversation = Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/api/v1/conversations `
  -Headers $headers -ContentType application/json -Body '{"title":"ATO Demo"}'
```

Use `http://localhost:8000/docs` with the bearer token, or the HTTP examples
above, to run this workflow:

1. `POST /api/v1/conversations/{conversation_id}/start` with a new
   `client_request_id` and confirm the greeting is returned.
2. Send `Help me prepare my tax return` to the conversation message endpoint and
   read the `tax_intake.id` from the final questionnaire SSE event.
3. Save all three answers with the current `version`: `first_tax_return=yes`,
   `work_expenses=[working_from_home,work_related_car]`, and
   `income_sources=[salary_wages]`. Use the version returned by each response for
   the next request.
4. Call `GET /api/v1/tax-intakes/{id}` to demonstrate refresh recovery, then call
   `/complete` with its current version and a new `client_request_id`.
5. Confirm the stream contains `retrieval.started`, `retrieval.completed`, a
   grounded `document_checklist`, and `summary_confirmation`. Every checklist
   item must have at least one citation ordinal.
6. Fetch the intake again and call `/summary` with `requested=true`, its current
   version, and a new `client_request_id`. The grounded `tax_summary` must reuse
   the checklist citation snapshots.

The following questions provide repeatable single-topic, clarification, and
unsupported-scope checks:

| Question | Expected result or source document ID |
| --- | --- |
| `Hello` | General chat, no retrieval or citations |
| `What car records are needed for 2025-26?` | `ato-car-expenses-toolkit` |
| `What working-from-home records are needed for 2025-26?` | `ato-working-from-home-expenses` |
| `What salary and wages records are needed for 2025-26?` | `ato-recruitment-consultants-income-deductions` |
| `What self-education records are needed for 2025-26?` | `ato-self-education-expenses` or `ato-tr-2024-3-self-education` |
| `What rental property records are needed for 2025-26?` | `ato-rental-property-records` |
| `What bank interest records are needed for 2025-26?` | `ato-bank-accounts-and-income-bonds` |
| `What car records do I need?` | Clarification requesting the tax year |
| `What car records are needed for 2024-25?` | Unsupported year; no grounded checklist |
| `Help with overseas income tax` | Unsupported topic; no factual tax answer or citations |

To verify failure closure, stop Milvus temporarily and call readiness:

```powershell
docker compose stop milvus
Invoke-WebRequest http://localhost:8000/health/live       # 200
Invoke-WebRequest http://localhost:8000/health/ready      # 503
docker compose up -d milvus
```

While Milvus is unavailable, an ATO document request ends with `message.failed`
and must not return an ungrounded checklist. Readiness returns to 200 after Milvus
is healthy again.

Known limitations: the reviewed corpus covers only the six manifest claim types
for 2025–26; source files are manually maintained and are not automatically
refreshed from the ATO; the default LLM and Embedding implementations are test
fakes; there is no file upload, external identity provider, production capacity
design, or high-availability Milvus; and generated output is information for
human review, not tax-agent advice or a tax return submission.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
```

The live OpenAI connectivity smoke is skipped by default. To run it explicitly
(it makes a network call and may incur cost), set the provider key/model and run:

```powershell
$env:SORTAX_RUN_OPENAI_SMOKE="1"
.\.venv\Scripts\python.exe -m pytest tests/llm_gateway/test_openai_live.py
```

The equivalent opt-in Qwen smoke test uses the Qwen settings above:

```powershell
$env:SORTAX_RUN_QWEN_SMOKE="1"
.\.venv\Scripts\python.exe -m pytest tests/llm_gateway/test_qwen_live.py
```

The opt-in classifier smoke covers all four intent routes and its forced-failure
fallback. It makes billable Qwen calls:

```powershell
$env:SORTAX_RUN_LIVE_INTENT_TESTS="1"
.\.venv\Scripts\python.exe -m pytest tests/intent/test_llm_classifier_live.py
```

Phase 4B includes an opt-in integration smoke against the already imported local
Milvus collection. Start the Milvus services first, then run:

```powershell
$env:SORTAX_RUN_MILVUS_SMOKE="1"
.\.venv\Scripts\python.exe -m pytest tests/rag/test_phase4b_live.py
```

The smoke performs one filtered retrieval for each of the six supported claim
types, merges the results, and verifies every grounding item has a 2025–26
citation ordinal. It does not call an external LLM or Embedding Provider.

Install Git hooks with:

```powershell
.\.venv\Scripts\python.exe -m pre_commit install --hook-type pre-commit --hook-type pre-push
```
