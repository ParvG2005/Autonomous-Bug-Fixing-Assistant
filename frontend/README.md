# Bugfix Assistant — Dashboard (Phase 12)

React + Vite + Tailwind dashboard: list runs, watch a fix stream in live (SSE), inspect the diff and
reasoning trace, and approve/reject at the C1 human gate.

## Develop

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /jobs|/metrics|/healthz -> :8000
```

Run the API alongside it (`bugfix-api`, default `:8000`). Override the proxy target with
`VITE_API_TARGET=http://host:port npm run dev`.

## Test & build

```bash
npm test           # vitest (jsdom) — api client, SSE hook, approve/reject flow
npm run build      # tsc --noEmit && vite build -> dist/
```

## Shape

- `src/api.ts` — typed client (relative URLs; `ApiError` carries the server detail).
- `src/hooks/useJobStream.ts` — EventSource over `GET /jobs/{id}/logs`.
- `src/components/` — `JobList`, `JobDetail` (status, runs, fix, live log, diff, reasoning,
  approve/reject), `StatusBadge`, `DiffView`.

In production, serve `dist/` from the API (or a static host) so the dashboard is same-origin and CORS
is unnecessary.
