# UI Control Plane — run everything from the frontend

**Date:** 2026-07-01
**Status:** Approved design, pending implementation plan
**Scope:** Single-user, local (not deployed). No auth layer yet.

## Goal

Make the React frontend the complete control surface. Today the UI is
read-mostly (list jobs, stream logs, approve/reject, list/promote findings);
all *inputs* live outside it — jobs come only from the GitHub webhook
(`issues.labeled` + `autofix`), repos are registered implicitly by that
webhook, discovery scans run from CLI/workers, and the draft-PR publish is
CLI-only (`bugfix-pr open --confirm`). This closes those four gaps.

## Non-goals

- No auth / multi-user. Single operator, API bound to localhost. **Before any
  deploy, add auth on the write endpoints** — this is a recorded follow-up.
- No changes to the agent loop, sandbox, or solve pipeline.
- No removal of the webhook or CLI paths; the UI is an additional entry point.

## Repo auth model: "URL now, connect later"

A repo can be added by URL with no GitHub App install (fix-only: public clone,
reproduce/fix/explain, **no PR**). A per-repo "Connect GitHub App" action later
resolves the install and upgrades it to publish-capable.

## Architecture

Three additive layers.

### 1. Data model (one Alembic migration)

- `Repo.installation_id` → **nullable**. `NULL` = fix-only; non-null =
  publish-capable. This nullable flag *is* the capability signal — no extra
  column. Existing webhook-created repos always set it, so they are unaffected.
- `Repo.clone_url` → new `String`, nullable. Set for URL-added repos so the
  cloner can fetch a public repo without the App resolving a clone URL.
- `Repo.gh_repo_id` is currently `unique, index, non-null`. URL-added repos have
  no `gh_repo_id` until connected → make it **nullable** (keep unique index;
  SQLite/Postgres both allow multiple NULLs under a unique index).

### 2. API — new write endpoints

All run in the API process **except** GitHub network I/O, which is delegated to
a worker (see Safety boundary).

| Method | Path | Body | Action |
|---|---|---|---|
| `GET` | `/repos` | — | List repos with capability badge (fix-only / publish-capable). |
| `POST` | `/repos` | `{clone_url}` | Parse `owner/name` from URL; create repo row, `installation_id=NULL`, `gh_repo_id=NULL`, store `clone_url`. |
| `DELETE` | `/repos/{id}` | — | Remove a repo (reject if it has live jobs). |
| `POST` | `/repos/{id}/connect` | — | Enqueue a worker task: GitHub App auth resolves `gh_repo_id` + `installation_id`; upgrade the row. |
| `POST` | `/jobs` | `{repo_id, body, title?}` | `ingest_manual_issue`: store `body` as untrusted `issue_body` artifact, create `trigger=MANUAL` queued job, `queue.enqueue`. Returns the job. |
| `POST` | `/repos/{id}/scan` | — | Enqueue the Phase 13 discovery scan worker for the repo. |
| `POST` | `/jobs/{id}/publish` | `{actor?}` | Assert approval via existing `assert_approved`; reject if repo `installation_id IS NULL`; enqueue publish worker. Returns the PR URL when done (poll job state / artifact). |

New service function `ingest_manual_issue(session, repo_id, body, title)` in
`app/db/jobs.py`, sibling to `ingest_labeled_issue`:
- Stores `body` as an `issue_body` ARTIFACT (untrusted; never inlined on JOB).
- Creates a `Job` with `trigger=JobTrigger.MANUAL`, `gh_issue_number=NULL`,
  `state=QUEUED`, default budget.
- Idempotency: not required (manual submit is explicit); each POST = one job.

### 3. Frontend

- **New "Repos" tab** (third nav tab beside Jobs/Findings):
  - List of repos, each with capability badge.
  - "+ Add repo" → URL field → `POST /repos`.
  - Per-row actions: "Scan" (`POST /repos/{id}/scan`), "Connect GitHub App"
    (`POST /repos/{id}/connect`, shown only when fix-only), "Delete".
- **"+ New Fix"** button on the Jobs tab → modal:
  - Repo dropdown (from `GET /repos`), textarea for issue text / stack trace,
    optional title → `POST /jobs` → on success select the new job so its live
    log streams immediately (reuses existing SSE).
- **"Publish draft PR"** button on `JobDetail`:
  - Visible only when job is approved **and** its repo is publish-capable.
  - On click → `POST /jobs/{id}/publish`; show resulting PR URL, or the
    rejection reason (unapproved / not publish-capable).

`frontend/src/api.ts` gains: `listRepos`, `addRepo`, `deleteRepo`,
`connectRepo`, `createJob`, `scanRepo`, `publishJob`. `types.ts` gains a `Repo`
type with a capability flag.

## Data flow

**New Fix:** UI form → `POST /jobs` → `issue_body` artifact stored → MANUAL job
`queued` → `queue.enqueue` → worker runs the existing solve pipeline → UI
streams logs (existing SSE) → approve/reject (existing) → publish (below).

**Publish:** UI button → `POST /jobs/{id}/publish` → API calls `assert_approved`
(C1 chokepoint) → enqueue publish worker → worker mints install token, opens
draft PR, discards token → PR URL recorded on the job/artifact → UI shows it.

## Safety boundary (load-bearing)

- **API process stays network-free.** All GitHub I/O — `connect`, `scan`,
  `publish` — runs in a worker, never in an API handler. Preserves secret
  isolation (SECURITY.md **C4**).
- **Publish keeps the C1 human gate.** `POST /jobs/{id}/publish` goes through the
  existing `assert_approved` chokepoint; no new bypass. It is the UI counterpart
  of `bugfix-pr open --confirm`, not a new write path to GitHub.
- **Untrusted input.** Manual `POST /jobs` body is stored as an artifact, never
  inlined on the JOB row — same handling as the webhook's issue body.
- **Localhost bind, no auth** — acceptable only because single-user, not
  deployed. Recorded non-goal: add auth before exposing write endpoints.
- **Capability checks.** `connect` and `publish` reject when `installation_id`
  is null; `publish` additionally rejects when not approved.

## Error handling

- Bad clone URL → `400` with parse reason.
- `connect` when App not installed on the repo → `409`, repo stays fix-only.
- `publish` unapproved → `409` "approval required"; not publish-capable → `409`
  "connect GitHub App first".
- `DELETE` repo with live jobs → `409`.
- Worker failures surface on the job's `failure_reason` (existing mechanism).

## Testing

- **Unit:** `ingest_manual_issue` (artifact stored, MANUAL trigger,
  enqueue called, no issue number); clone-URL parsing; publish rejects
  null-install and unapproved.
- **API:** each new endpoint, happy path + each reject path.
- **Frontend:** New Fix form posts then selects the job; Publish button gating
  (approved + publish-capable only); Repos tab add/scan/connect/delete calls.

## Migration safety

The migration only relaxes constraints (non-null → nullable) and adds a nullable
column — backward-compatible, no data backfill. `alembic check` must stay clean.
