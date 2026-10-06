# Sortax Chat Backend Data Classification

This document is a Phase 0 implementation constraint. If a later feature cannot
meet these rules, it requires an explicit architecture and compliance review.

## Classification levels

| Level | Examples | Storage and logging rule |
| --- | --- | --- |
| Public | OpenAPI schema, generic health status, manually selected ATO public source files | May be exposed without authentication when explicitly documented; the application still serves ATO content only through authenticated chat |
| Internal | Request ID, opaque resource IDs, model name, latency, token counts, status codes | Structured logs are allowed; access remains limited to operators |
| Confidential | Conversation title, redacted prompt/response, tenant configuration, usage and cost | Encrypt in transit and at rest; access by tenant and owner; log only when redacted and truncated |
| Restricted | Raw prompt/response, accounting records, tax identifiers, bank details, identity data | Store only for the required product purpose; never place raw values in logs, traces, metrics, fixtures, or error responses |
| Secret | OpenAI API Key, JWT signing key, bearer token, database credentials | Environment variable or Secret Manager only; never persist in application tables or emit in any observability channel |

Redaction lowers exposure but does not make content public. Redacted prompts and
responses remain Confidential because identifiers may survive or be inferred.

## Environment rules

### Local development and automated tests

- Use only simulated data or data that has been irreversibly de-identified.
- Use `FakeProvider` by default and fail if a test attempts an external model call.
- Do not copy production databases, logs, prompts, responses, keys, or tokens.
- An OpenAI API Key may be supplied only for an explicit manual smoke test.

### Production gate

Before enabling `OpenAIProvider` with customer data, record approval for:

- application deployment and model-processing regions;
- cross-border processing rules;
- the current OpenAI account, contract, and data-control configuration meeting
  the requirement that inputs are not used for training;
- retention periods for audit events and redacted operational logs;
- applicable accounting, privacy, and customer-contract obligations.

An adapter implementation is not evidence that these conditions are satisfied.

## Data flow controls

1. The API authenticates the JWT and derives trusted `user_id` and `tenant_id`.
2. Authorization verifies both tenant ownership and user ownership.
3. The safety layer rejects oversized input and applies configured policy checks.
4. Only the minimum prompt required for the response is sent to the selected Provider.
5. Raw messages are stored in PostgreSQL as the product record; Redis is not a permanent store.
6. Observability receives metadata and optionally redacted, truncated content only.
7. Provider errors are normalized before reaching clients or logs.

## ATO RAG data boundaries

The Demo knowledge base contains only public ATO material selected and downloaded
by a project maintainer. It must not contain user uploads, chat messages, customer
records, or tenant-private documents.

### Offline ingestion flow

1. A maintainer downloads an ATO HTML, PDF, TXT, or Markdown file outside the application.
2. The maintainer records its ATO URL, title, `claim_type`, tax year, access date,
   media type, and local path in `manifests/ato/sources.yaml`.
3. The ingestion CLI restricts reads to the configured ATO data directory and
   validates the manifest, allowed ATO host, file type, and file size.
4. Parsed text is normalized, chunked, and sent to the configured Embedding Provider.
5. Milvus receives only public ATO chunk text, vectors, document/chunk IDs, content
   hash, title, source URL, `claim_type`, tax year, access date, and ingestion version.
6. Import summaries may record document IDs, hashes, counts, timings, and normalized
   failures, but must not duplicate chunk text in logs.

### Online retrieval flow

1. The authenticated question remains Restricted conversation data in PostgreSQL.
2. Before query embedding, the safety layer removes identifiers and reduces the
   question to the minimum retrieval query needed for `claim_type` and tax year.
3. The minimized query sent to an external Embedding Provider remains Restricted
   in transit. It is not stored in Milvus and is not logged; only a non-reversible
   query hash and provider/configuration metadata may be persisted.
4. Milvus is queried with the embedding plus `claim_type` and tax-year filters.
   Milvus must never receive `tenant_id`, `user_id`, raw chat text, or customer data.
5. Selected public chunks are passed to the LLM in a bounded evidence section.
   The LLM receives only the minimum chat context and evidence required to answer.
6. PostgreSQL stores the final answer, retrieval-run metadata, and an immutable
   citation snapshot. Logs and traces store neither the query nor chunk bodies.
7. Missing classification data causes clarification. Missing evidence or an
   unavailable Embedding/Milvus dependency fails closed; the LLM must not produce
   an ungrounded ATO document checklist.

### RAG classifications and retention

| Data | Classification | Location and rule |
| --- | --- | --- |
| Downloaded ATO source and parsed chunks | Public | Local configured directory and Milvus only; maintainer-controlled ingestion |
| ATO chunk embeddings | Internal | Milvus only; tied to one provider/model/version and rebuilt on model changes |
| Raw user question and chat context | Restricted | PostgreSQL product record; never stored in Milvus or observability |
| Minimized/redacted embedding query | Restricted | Transient provider request only; persist only a non-reversible hash |
| Retrieval configuration, scores, latency, document/chunk IDs | Internal | PostgreSQL retrieval run and redacted operational telemetry |
| Answer and citation snapshot | Confidential or Restricted with its conversation | PostgreSQL, subject to tenant/user authorization and conversation deletion |

The deterministic `FakeEmbeddingProvider` is the default for automated tests and
local contract work. A real Embedding Provider is opt-in and is subject to the same
production gate and no-training requirement as the LLM Provider.

## Redaction contract

The shared redactor must cover at least:

- JWTs and API keys;
- tax and government identity numbers;
- bank and payment account numbers;
- email addresses and telephone numbers;
- configured customer-specific identifiers.

If redaction fails, log metadata only: request ID, tenant ID, user ID, model,
token usage, latency, content length, and a non-reversible content hash. Never
fall back to logging raw content.

## Retention and deletion

- Conversations and message content expire after 180 days and are physically deleted.
- A user deletion physically deletes the owned conversation and all message content.
- The same deletion removes related generation runs, retrieval runs, and citation
  snapshots, but does not delete the global public ATO source collection.
- An active generation is cancelled and settled before deletion.
- Deletion is idempotent and returns the same external result for missing or inaccessible resources.
- The deletion audit event contains identifiers, actor, result, and time, but no copied message content.
- Audit and redacted-log retention periods remain production launch gates.

Backups and replicas must eventually honor the same deletion policy. Their exact
purge window depends on the production infrastructure and must be documented
before launch.

## Prohibited MVP actions

The chat backend may explain or draft, but must not execute:

- payments or fund transfers;
- tax return submission;
- posting an accounting journal or modifying a ledger;
- changes to an external accounting system.

User attachments, tenant-private knowledge bases, automated ATO crawling, and
external tool calls are excluded from the MVP. Expanding RAG beyond the curated
public ATO collection requires a new data-flow and threat review.
