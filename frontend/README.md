# Bugfix Assistant — Dashboard (Phase 12)

React + Vite + Tailwind dashboard: list runs, watch a fix stream in live (SSE), inspect the diff and
reasoning trace, and approve/reject at the C1 human gate.

## Develop

```bash
cd frontend
npm install
npm run dev        # Phase 14: boots the WHOLE stack (compose + migrate + bootstrap + API + worker + vite)
npm run dev:web    # frontend only — vite on :5173, proxies /jobs|/metrics|/healthz|/findings|/scans -> :8000
```

`npm run dev` is the one-command local stack (see the root README Quickstart): it wipes-then-scrapes
open issues into the pipeline on startup (dev-only, `APP_ENV=local`). For a frontend-only loop against
a separately-run API (`bugfix-api`, default `:8000`), use `npm run dev:web` and override the proxy
target with `VITE_API_TARGET=http://host:port npm run dev:web`.

## Test & build

```bash
npm test           # vitest (jsdom) — api client, SSE hook, approve/reject flow
npm run build      # tsc --noEmit && vite build -> dist/
```

## Shape

- `src/api.ts` — typed client (relative URLs; `ApiError` carries the server detail).
- `src/hooks/useJobStream.ts` — EventSource over `GET /jobs/{id}/logs`.
- `src/components/` — `JobList`, `JobDetail` (status, runs, fix, live log, diff, reasoning,
  approve/reject), `StatusBadge`, `DiffView`, `FindingsList` (Phase 13 discovery tab — list
  candidates + one-click promote).

In production, serve `dist/` from the API (or a static host) so the dashboard is same-origin and CORS
is unnecessary.
