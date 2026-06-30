# Autonomous Bug-Fixing Assistant

Given a GitHub issue or stack trace on a Python repo, this system clones the repo into a
sandbox, reproduces the bug, localizes it, proposes a fix, verifies it against tests, explains
its reasoning, and opens a **draft** pull request for human review — never pushing or merging
without recorded human approval.

Design docs live in [`docs/`](docs/README.md). Build order is in
[`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md).

## Status

- ✅ **Phase 0 — scaffold**: target layout, `pyproject` (Python 3.12), ruff + mypy + pytest,
  pre-commit, CI, base sandbox image, `.env.example`.
- ✅ **Phase 1 — repo brain**: clone, tree-sitter Python symbol index, `read_file` / `search`
  (ripgrep) / `find_symbol`, hybrid-retrieval interface (vector fallback optional), CLI.
- ✅ **Phase 2 — test runner + sandbox v1**: pytest detection; execution inside a capped,
  network-isolated, non-root, read-only Docker container (local subprocess fallback for dev);
  pass/fail parsing + native-traceback `{file, line, function}` frame parser; `bugfix-run` CLI.
- ✅ **Phase 3 — agent loop (core)**: Anthropic tool-use loop (`claude-opus-4-8`, adaptive
  thinking) with six tools — `read_file` / `search` / `find_symbol` / `edit_file` /
  `run_tests` / `run_command` — every call gated by the `app.core.allowlist` validator before
  dispatch and every execution tool run inside the sandbox; a planning step, a retry/token/
  time budget, and an authoritative final-test verification; `bugfix-agent` CLI.
- ✅ **Phase 4 — issue → reproduce → localize → fix → explain** ⭐ core milestone: parse raw
  issue text / stack traces into a structured task (`app.agent.issue`); rank suspect files from
  traceback frames + referenced paths + symbols (`app.agent.localize`); drive the agent to
  reproduce (writing a failing test if none exists), fix, and self-correct; **edit guardrails**
  (`app.agent.guardrails`) flag — never silently edit — CI config / lockfiles / secrets and cap
  the diff size; a deterministic Markdown reasoning writeup + change summary (`app.agent.writeup`);
  orchestrated by `app.agent.solve` and the `bugfix-agent solve` CLI.
- ✅ **Phase 5 — GitHub integration (human-gated)** ⭐ never cut: GitHub App install-token
  auth (`app.vcs.auth`, RS256 JWT → short-lived installation token, redacted in memory); a
  REST client with **no merge / no push-to-base / draft-PR-only** surface (`app.vcs.github`,
  Git Data API commit); the **APPROVAL gate** (`app.vcs.approval`) — append-only, latest-wins,
  with `assert_approved` the single chokepoint; the **sole remote-write path**
  (`app.vcs.publish`) that asserts approval *first*, then mints-uses-discards the token, opens a
  **draft** PR, and posts the reasoning as a comment; a Phase 4 → bundle bridge
  (`app.vcs.bundle`) and the `bugfix-pr` CLI. Maps to SECURITY.md **C1** (human gate) and
  **C4** (secret isolation). Real-PR acceptance is marked `integration` + STOP-AND-ASK.
- ✅ **Phase 6 — Backend API + data model + webhook**: FastAPI (async) control plane;
  SQLAlchemy 2.0 async models for repos/jobs/runs/artifacts/fixes/approvals/code-chunks
  (`app.models`, mirroring DATA_MODEL.md) on portable column types (one schema serves Postgres
  and the SQLite unit DB); Alembic from day one (`migrations/`, initial migration applies +
  `alembic check` clean); an async engine/session factory (`app.db.session`); the **HMAC-SHA256
  webhook verifier** (`app.api.security`, constant-time, secret never logged); and the sole
  ingestion path (`app.db.jobs.ingest_labeled_issue`) — an `issues.labeled` delivery with the
  `autofix` label upserts the repo, stores the untrusted issue body as an ARTIFACT, and enqueues
  one **queued** JOB, **idempotently** (a repeat delivery returns the live job). `bugfix-api` CLI.
- ✅ **Phase 7 — Async workers**: Redis + arq fire-and-forget queue (`app.workers.queue`, enqueues
  **deduped by job id**); a **job state machine** (`app.workers.state`, `queued → running →
  awaiting_approval → approved → done`, plus `failed`/`rejected`) that refuses illegal moves; the
  **pipeline** (`app.workers.pipeline`) that clones into one **isolated per-job workspace**, runs
  the Phase 4 reproduce→fix→verify inside the sandbox, persists RUN/FIX/ARTIFACT rows + cost, and
  routes a verified fix to the **human gate** (`awaiting_approval` — never auto-published, C1);
  **crash recovery** (`app.workers.recovery`) sweeps `running` jobs back to `queued` on worker
  startup; and read-only status/SSE-log endpoints (`GET /jobs`, `/jobs/{id}`, `/jobs/{id}/logs`).
  `bugfix-worker` CLI (also `arq app.workers.worker.WorkerSettings`).
- ✅ **Phase 8 — Multi-language adapters**: a **language-adapter plugin layer** (`app.runner.adapters`)
  factors out everything framework-specific behind one `LanguageAdapter` contract — `detect`,
  `install_command`, `build_command`, `parse_frames`, `parse_result`. Three adapters ship: **Python**
  (pytest, wraps the original runner), **JS/TS** (`node --test`, zero-dependency TAP), and **Go**
  (`go test`). A generic `run_tests` (`app.runner.run`) detects the language and dispatches, so the
  agent loop and worker pipeline never name a language. Per-language sandbox base images
  (`docker/sandbox.{python,node,go}.Dockerfile`) carry each toolchain, selected by detected language.
  Acceptance: a verified red→fix→green run in each of Python, JS/TS, Go
  (`tests/integration/test_multilang_acceptance.py`).
- ✅ **Phase 13 — proactive bug discovery** (optional): `app.discovery` turns a repo into a *job
  source*. Detectors (`sources/`: existing-test failures, mypy/ruff static analysis, diff/hotspot)
  emit cheap, noisy `Candidate`s in the sandbox; `triage` dedups (fingerprint, unique per repo),
  ranks (confidence × severity), and budget-caps them; a survivor becomes the **same synthetic
  `IssueTask`** the webhook produces and a `trigger="discovery"` job — so reproduce → fix → verify →
  human-gated draft PR is unchanged. **Reproduction is the precision filter.** New `scan`/`finding`
  tables, `bugfix-scan` CLI (spend-gated like eval), `/findings` + `/scans` API, and a dashboard
  Findings tab with one-click promote.
- ✅ **Phase 14 — one-command local dev** (optional, dev-only): `npm run dev` boots the whole
  stack and opens a freshly-populated dashboard (see Quickstart). New `bugfix-bootstrap`
  (`app.db.bootstrap`): `--reset` wipes job tables (guarded to `APP_ENV=local`), `--scrape` pulls
  open GitHub issues (reusing Phase 5 auth) and enqueues each via the existing ingest path
  (`trigger="scrape"`, capped by `SCRAPE_MAX_JOBS`). The human gate is unchanged.
- ⬜ Phases 9, 15–16: see the build plan (Deploy is now Phase 15, Docs Phase 16).

## Quickstart

Requires [`uv`](https://docs.astral.sh/uv/) and `ripgrep` on PATH.

```bash
uv sync --dev              # create the venv, install deps (Python 3.12)
uv run pytest -m "not integration"   # unit tests (offline)
uv run ruff check . && uv run mypy app
```

### Repo brain CLI

```bash
# Clone a repo into a workspace, then ask where a symbol lives.
uv run repo-brain clone https://github.com/psf/cachetools ./workspaces/cachetools
uv run repo-brain where  ./workspaces/cachetools LRUCache
uv run repo-brain search ./workspaces/cachetools "def get" --fixed
uv run repo-brain read   ./workspaces/cachetools src/cachetools/__init__.py --start 1 --end 40
```

`where` prints where the symbol is **defined** (exact, from the tree-sitter index) and **used**
(word-boundary ripgrep), which is the Phase 1 acceptance behavior.

### Test runner CLI

```bash
# Build the sandbox image once (Docker; needed for the isolated run path).
docker build -t bugfix-sandbox:latest -f docker/sandbox.Dockerfile .

# Detect the framework, then run the workspace's tests in a sandbox.
uv run bugfix-run detect ./workspaces/some-repo
uv run bugfix-run test   ./workspaces/some-repo          # Docker when present
uv run bugfix-run test   ./workspaces/some-repo --local  # subprocess fallback (no Docker)
```

`test` prints pass/fail counts and, per failing test, the exception message and the parsed
`{file, line, function}` frames — the Phase 2 acceptance behavior. Docker-backed integration
tests are marked `docker`; run them with `uv run pytest -m docker`.

### Agent CLI

```bash
# Needs ANTHROPIC_API_KEY (see .env.example). The agent reads/searches the repo,
# edits the source, runs tests in the sandbox, and self-corrects within a budget.
uv run bugfix-agent fix ./workspaces/some-repo \
  --task "test_foo.py fails: bar() returns the wrong value; fix the bug." \
  --target test_foo.py     # restrict the final verification run
uv run bugfix-agent fix ./workspaces/some-repo --task "..." --local   # no Docker
```

`fix` prints the plan, the unified diff of its edits, and a `RESOLVED` / `UNRESOLVED`
verdict from an authoritative final test run — the Phase 3 acceptance behavior. The
API-backed acceptance test is marked `integration` (skips without a key); run it with
`uv run pytest -m integration`.

```bash
# Phase 4: give it a raw issue (or a stack trace) and get a verified patch + writeup.
uv run bugfix-agent solve ./workspaces/some-repo \
  --issue "divide(1, 0) raises ZeroDivisionError; it should return 0. See calc.py." \
  --writeup-out fix.md        # write the reasoning writeup to a file
uv run bugfix-agent solve ./workspaces/some-repo --issue-file issue.txt --local
```

`solve` parses the issue, **ranks suspect files**, drives the agent to reproduce (writing a
failing test when none exists), fix, and verify, then prints the diff plus a Markdown reasoning
writeup — the Phase 4 core milestone. Edits to CI config, lockfiles, or secret-bearing files are
**flagged and refused, never silently applied**, and the diff is size-capped. The API-backed
acceptance is marked `integration`.

### Draft-PR CLI (the human gate)

```bash
# The remote-write plane. Decisions persist to ./.bugfix/approvals.jsonl (append-only).
uv run bugfix-pr approve job-123 --actor parv --note "looks right"
uv run bugfix-pr status  job-123
uv run bugfix-pr reject  job-123 --actor parv      # a reversal is a new record

# Open the DRAFT PR for an approved job (the ONLY remote write in the system).
# Refuses without an `approved` record; --confirm is required to actually push.
uv run bugfix-pr open    job-123 --bundle fix.json --confirm
```

The `open` path asserts the APPROVAL record **before** minting any GitHub token (SECURITY.md
C1); the short-lived installation token is minted inside `app/vcs`, used, and discarded, never
logged (C4). PRs are always `draft=true`; there is no merge or push-to-default code path
anywhere in the client. Opening the first real PR is a **STOP-AND-ASK** gate — the acceptance
test (`tests/integration/test_pr_acceptance.py`) only runs with a disposable test repo + App
credentials in the environment.

### Backend API + webhook

```bash
# Bring up Postgres (compose) and apply migrations.
docker compose up -d postgres
uv run alembic upgrade head

# Serve the control plane (health + GitHub webhook).
uv run bugfix-api                       # honors API_HOST / API_PORT / DATABASE_URL
```

Point a GitHub App webhook (issues events, `application/json`, with `GITHUB_WEBHOOK_SECRET`) at
`POST /webhooks/github`. Each delivery is HMAC-SHA256 verified before its body is trusted; a bad
signature is a flat 401. Labeling an issue `autofix` enqueues exactly one **queued** job (repeat
deliveries are idempotent) — the Phase 6 acceptance behavior, covered offline against SQLite in
`tests/unit/test_webhook.py`. Any other event, action, or label is acknowledged and ignored.

### Proactive discovery (Phase 13)

```bash
# Scan a registered repo's local checkout for latent bugs. Without --confirm it
# records candidates as findings only (no spend); --confirm promotes the top
# findings to jobs that then flow to the existing approve/draft-PR gate.
uv run bugfix-scan run --repo owner/name --path ./workspaces/name
uv run bugfix-scan run --repo owner/name --path ./workspaces/name --max-jobs 5 --confirm
```

Discovery reads and executes untrusted code, so detectors run **only in the sandbox** — no new
trust boundary, and the only GitHub mutation remains the human-gated draft PR. A re-scan never
refiles a known finding (fingerprint dedup). The dashboard's **Findings** tab lists candidates and
promotes them with one click. Offline-tested end-to-end in
`tests/integration/test_discovery_acceptance.py`.

### One-command local dev (`npm run dev`, Phase 14)

```bash
cp .env.example .env      # set APP_ENV=local, ANTHROPIC_API_KEY, SCRAPE_REPOS, GitHub App creds
cd frontend && npm install
npm run dev               # boots the whole stack, opens a freshly-populated dashboard
```

`npm run dev` (dev-only) sequences then supervises: `docker compose up -d postgres redis` (waits
on 5432/6379) → `alembic upgrade head` → `bugfix-bootstrap --reset --scrape` (**wipe then scrape**:
empty the job tables, pull open issues from `SCRAPE_REPOS`/`SCRAPE_LABEL`, enqueue up to
`SCRAPE_MAX_JOBS`) → `concurrently` runs `bugfix-api` + `bugfix-worker` + `vite` under one Ctrl-C.
Open http://localhost:5173 and watch the scraped issues move `queued → running →
awaiting_approval`. Scraped jobs still stop at the C1 human gate; re-running is idempotent.

> `--reset` deletes dev job history and the scrape auto-enqueues token-spending jobs — both gated
> (`APP_ENV=local`, `SCRAPE_MAX_JOBS`, `SCRAPE_ON_START=false` to disable). Deploy (Phase 15) uses
> its own non-destructive start and never wipes or auto-scrapes. For a frontend-only loop against a
> separately-run API, use `npm run dev:web`.

## Layout

```
app/
  api/        HTTP surface — FastAPI app + webhook + findings (Phase 6+, 13)
  db/         async engine/session + ingestion + discovery/bootstrap (Phase 6+, 13, 14)
  discovery/  proactive bug-hunt: detectors, triage, promote (Phase 13)
  models/     SQLAlchemy 2.0 models (Phase 6+)
  agent/      tool-use loop + allowlist (Phase 3+)
  vcs/        GitHub App + draft PR — sole remote-write owner (Phase 5+)
  sandbox/    ephemeral container isolation (Phase 2+)
  index/      repo brain: clone, symbols, search, retrieval  ← Phase 1
  runner/     multi-language test detection + run + parse; adapters/ (Phase 2, 8+)
  workers/    arq tasks + job state machine (Phase 7+)
  models/     SQLAlchemy + Alembic (Phase 6+)
  core/       settings, secrets, tool allowlist
  telemetry/  structlog + Langfuse + cost (Phase 10+)
frontend/  eval/  docker/  deploy/  tests/
```

## Security model

The control/execution plane split (see [`docs/SECURITY.md`](docs/SECURITY.md) and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §5) is load-bearing: untrusted repo code runs
only in sandboxes with no secrets and no egress, and remote-write lives in a single authorized
code path gated on a human approval record.
