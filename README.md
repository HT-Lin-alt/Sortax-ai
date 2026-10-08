# Sortax Chat Backend

The project has completed the Phase 0R contracts, ATO ingestion and Milvus
retrieval path, persistence foundation, and the Phase 5A–5C chat implementation.
The billable real-provider Demo remains an explicit operator-run acceptance step.

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

After creating `.env` and replacing its placeholder secrets, start the API,
PostgreSQL, Redis, Celery worker, and Milvus standalone together. Milvus also
starts its required local etcd and MinIO services:

```powershell
docker compose up --build
```

The first start downloads the pinned container images and can take several
minutes. The API container applies the Alembic migration before starting.
Readiness succeeds only after PostgreSQL, Redis, and Milvus are reachable. Verify:

```powershell
Invoke-RestMethod http://localhost:8000/health/ready
docker compose ps
```

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

Fake-mode evidence and citations are visibly marked as fake and must not be treated
as ATO advice. With Milvus enabled, grounded answers use the imported ATO chunks
and persist citation snapshots. A controlled real-provider run is still required
before declaring the complete Phase 5 acceptance gate passed.

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

Install Git hooks with:

```powershell
.\.venv\Scripts\python.exe -m pre_commit install --hook-type pre-commit --hook-type pre-push
```
