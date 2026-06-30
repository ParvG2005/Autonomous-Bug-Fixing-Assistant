# Phase 14 — One-command local dev (`npm run dev`)

> Status: **built.** `app/db/bootstrap.py` (`bugfix-bootstrap`: `--reset` guarded to
> `APP_ENV=local`, `--scrape` via Phase 5 auth), `GitHubClient.list_open_issues`, the
> `frontend/package.json` `npm run dev` orchestration (`concurrently` + `wait-on`), and the
> `SCRAPE_*` settings all ship; offline-tested in `tests/unit/test_db_bootstrap.py`. Slots **after
> Phase 13, before Deploy (now Phase 15)**. A
> developer-experience phase: a single `npm run dev` boots the whole stack and bootstraps a fresh,
> populated dashboard. Dev-only — none of this runs in a deployed environment.

## 1. Goal

Today the stack is started by hand: `docker compose up`, `alembic upgrade`, `bugfix-api`,
`bugfix-worker`, and the Vite dev server in separate terminals. Phase 14 collapses that into **one
command**: `npm run dev` brings up infra, applies migrations, **scraps (wipes) all existing
issues/jobs to a clean slate**, **scrapes open GitHub issues and enqueues them**, and launches API
+ worker + frontend together — so the dashboard opens already populated with freshly-pulled work.

"Scraps all the issue when the website is started" is implemented as **wipe-then-scrape**: reset the
job tables to empty, then pull open GitHub issues and enqueue a job for each.

## 2. What `npm run dev` does (orchestration)

`frontend/package.json` `dev` script becomes the single entry point, using `concurrently` +
`wait-on` to sequence and supervise the processes:

```
npm run dev
 ├─ 1. docker compose up -d postgres redis        # infra (waits for healthchecks)
 ├─ 2. uv run alembic upgrade head                # schema
 ├─ 3. uv run bugfix-bootstrap --reset --scrape   # WIPE then SCRAPE+enqueue (see §3)
 └─ 4. concurrently:
        ├─ uv run bugfix-api                       # :8000
        ├─ uv run bugfix-worker                    # drains the queue
        └─ vite                                    # :5173 dashboard
```

Steps 1–3 run to completion first (gated by `wait-on` on the Postgres/Redis ports + a healthcheck);
step 4 runs the three long-lived processes in parallel with prefixed, colorized logs and
single-Ctrl-C teardown. A root `package.json` or a `Makefile`/`justfile` target may wrap this so it
can also be launched from the repo root, but the canonical command stays `npm run dev`.

## 3. Startup bootstrap: wipe + scrape (`bugfix-bootstrap`)

A new small CLI (`app/db/bootstrap.py` → `bugfix-bootstrap`) does two things, both **guarded to
dev only**:

1. **`--reset` (wipe / "scrap"):** truncate `job`, `run`, `artifact`, `fix`, `approval` (and
   `scan`/`finding` if Phase 13 landed). Leaves `repo` rows. **Refuses to run unless
   `APP_ENV=local`** — a hard guard so this can never wipe a real database.
2. **`--scrape`:** using the Phase 5 GitHub App auth, list **open issues** for the configured
   repo(s) (default filter: the `AUTOFIX_LABEL`; `--all-issues` to ignore the label), and run each
   through the **same `ingest_labeled_issue` path the webhook uses** — storing the untrusted issue
   body as an ARTIFACT and enqueuing a `queued` JOB (`trigger="scrape"`). Idempotent: re-running
   after a `--reset` re-creates them; without `--reset` it dedupes against live jobs.

Because scraped issues flow through the **existing** ingest → queue → worker pipeline, the worker
picks them up immediately and the dashboard shows them moving `queued → running →
awaiting_approval`. Nothing about the fix loop or the human gate changes.

## 4. Config / new settings

```
# .env (dev)
APP_ENV=local                 # REQUIRED for --reset to be allowed
SCRAPE_ON_START=true          # let npm run dev run the bootstrap
SCRAPE_LABEL=autofix          # which issues to pull (empty/--all-issues = all open)
SCRAPE_MAX_JOBS=10            # safety cap on how many jobs a scrape enqueues
SCRAPE_REPOS=owner/repo,...   # which installed repos to scrape
```

## 5. Safety (this phase adds two sharp edges — both gated)

- **Destructive wipe.** `--reset` deletes job history. Guarded by `APP_ENV=local`; in `ci`/`prod`
  it errors out and does nothing. Never wired into the deployed start command (Phase 15).
- **Auto-enqueue spends tokens + auto-runs the autonomous pipeline.** Scraping N open issues
  enqueues N fix jobs that call the model. Bounded by `SCRAPE_MAX_JOBS` and the per-job budgets
  from Phase 3; `SCRAPE_ON_START=false` disables it. The **human gate is unchanged** — scraped
  jobs still stop at `awaiting_approval` and never open a PR without approval (C1).
- **Secrets** (GitHub App key) come from `.env` at runtime only, never committed (C4).
- **No new trust boundary.** Scraped issue text is untrusted and handled exactly like webhook
  input (stored as an artifact, run in the sandbox).

## 6. Deliverables

- `app/db/bootstrap.py` + `bugfix-bootstrap` console script (`--reset`, `--scrape`, `--all-issues`,
  `--max-jobs`, repo filter); `APP_ENV=local` guard on `--reset`.
- A GitHub "list open issues" call in `app/vcs` (read-only, reuses installation-token auth).
- `frontend/package.json` `dev` orchestration via `concurrently` + `wait-on`; dev deps added under
  `frontend/` only.
- `.env.example` gains `SCRAPE_ON_START`, `SCRAPE_LABEL`, `SCRAPE_MAX_JOBS`, `SCRAPE_REPOS`.
- Docs: a "Quickstart: `npm run dev`" section in the root README.

## 7. Acceptance

`APP_ENV=local npm run dev` →
1. Postgres + Redis come up (compose), migrations apply.
2. The job tables are emptied, then open issues from the configured repo are scraped and enqueued.
3. API, worker, and the Vite dashboard are all running; opening `localhost:5173` shows the
   scraped issues as jobs already progressing through the pipeline.
4. Re-running `npm run dev` yields the same clean, freshly-populated state (idempotent).

Offline-testable like the rest: the bootstrap's reset + ingest paths unit-tested against SQLite
with a fake GitHub issue lister; the orchestration script itself is a thin process launcher.

## 8. Dependencies & cut policy

- **Depends on:** 5 (GitHub read issues), 6 (ingest + DB), 7 (worker/queue), 12 (frontend). Phase
  13 (discovery) is **not** required — scraping pulls *existing* GitHub issues (reactive), distinct
  from discovery's *found* candidates.
- **Cut policy:** optional, dev-DX only — off the critical path to the Definition of Done. If cut,
  developers use the manual multi-terminal startup documented in `SMOKE_TEST.md`.
- **Relation to Phase 15 (Deploy):** deploy uses its own non-destructive start (migrations only, no
  wipe, no auto-scrape); the `--reset`/`SCRAPE_ON_START` machinery is strictly local.
