# Sortax frontend

The frontend includes the F0 engineering foundation, the F1 visual system, the
F2 live conversation flow, and the F3 OpenAPI-based tax questionnaire flow. In
development it obtains a short-lived local token in memory, restores the most
recent conversation and intake, starts a new greeting, and consumes POST-based
SSE chat and checklist responses.

## Local development

Start the FastAPI backend on `http://127.0.0.1:8000`, then run:

```powershell
cd frontend
npm install
npm run generate:types
npm run dev
```

Vite serves the SPA on `http://127.0.0.1:5173` and proxies `/api` and `/health`
to FastAPI. Tokens remain caller-owned and are passed to API functions in memory;
the frontend does not persist them.

Open `http://127.0.0.1:5173/?fixtures=1` to view the complete F1 structured-message
gallery without connecting to the API. The live route stores only the recent
conversation ID and an unfinished start idempotency key in local storage; tokens
and message bodies remain in memory.

The F3 client follows `docs/openapi.yaml`: answer PUT requests send
`selected_options` plus `version`, and completion sends the latest `version`.
The current in-progress backend tax-intake response models must be aligned with
that contract before live F3 integration can be accepted; the frontend contract
flow is covered by Playwright route fixtures in the meantime.

## Quality gates

```powershell
npm run check:types
npm run typecheck
npm run lint
npm run test
npm run build
npm run test:e2e
```

Use `npm run test:e2e:update` only when an intentional visual change requires new
390×844, 430×932, and 484×1024 screenshot baselines.

`src/api/generated-types.ts` is generated only from `../docs/openapi.yaml`.
Run `npm run check:types` in CI so contract changes cannot silently leave stale
frontend types.
