# Sortax frontend

The frontend currently includes the F0 engineering foundation and the F1 static
visual system for the mobile-first Sortax chat client. The F1 fixture timeline
demonstrates text messages, guided questions, completed answers, retrieval,
document checklist citations, summary confirmation, and a sourced tax summary.

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
