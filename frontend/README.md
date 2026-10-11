# Sortax frontend

Phase F0 provides the React 19, strict TypeScript, Vite, OpenAPI contract, and test
foundation for the mobile-first Sortax chat client.

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

`src/api/generated-types.ts` is generated only from `../docs/openapi.yaml`.
Run `npm run check:types` in CI so contract changes cannot silently leave stale
frontend types.
