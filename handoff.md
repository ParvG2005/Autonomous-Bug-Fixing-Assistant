# Handoff — Autonomous Bug-Fixing Assistant

> Running progress log. Update this at the end of every working session: what got done, what's
> left, and anything the next session needs to know. Most recent entry on top.

## Session note — 2026-07-01: connect-repo + agent-loop fixes (on `main`)

Live-debugging `ParvG2005/Workflow` through the UI surfaced four fixes, all shipped to `main`:

- **`fedc90f`** — `parse_repo_url` now accepts GitHub web-UI URLs (`/tree/<ref>`, `/blob/…`,
  `/pull/N`, `/commit/<sha>`) instead of rejecting them ("not a GitHub repo url"). Suffix stripped;
  branch/PR stays a separate per-job `ref`. Also fixed `resolve_repo_installation`: it authed
  `GET /repos/{full_name}` with the **App JWT** → HTTP 401 (JWT only valid on app-level endpoints).
  Reordered: resolve installation via JWT → mint installation token → repo lookup **with the token**.
  Plus made `test_mint_requires_configured_credentials` hermetic (`_env_file=None`) so a populated
  local `.env` can't leak real creds into unit tests.
- **`5f4d74f`** — `bootstrap.py` ran `asyncio.run()` inside `run_bootstrap`'s live event loop
  ("cannot be called from a running event loop"); now runs the identity fetch on a worker thread.
  `dev:bootstrap` dropped `--scrape` so `npm run dev` resets the DB without auto-scraping.
- **`d6bbdee`** — agent loop treated any `stop_reason != "tool_use"` as `COMPLETED`, so a model that
  narrated its plan ("the plan has already been fully executed") without calling `edit_file` stopped
  at iteration 1 with an empty diff / UNRESOLVED, budget unused. Now: end-turn with **zero edits** →
  nudge to actually use the tools, bounded by `_MAX_CONTINUE_NUDGES = 2`. Verify gate had correctly
  refused to publish the empty fix — safety held; this stops the wasted run.

**Known-open (not bugs, design calls):** (1) proactive discovery scans the repo **default branch**
only (`main`), so it never targets `autofix-test` where the real issues live — discovery-promoted
jobs carry no `ref`. Use the manual "New Fix" path with `ref=autofix-test` to fix those. (2) The
service publish path is GitHub-App-only (no PAT fallback); a `.pem` in `.env` must be a multiline
double-quoted value. GitHub App `blah-blah-test` (app id `4184497`) is installed on `ParvG2005`
(installation `143570572`, selected repos incl. `Workflow`) and verified end-to-end.

**Reminder:** long-lived `bugfix-worker`/`bugfix-api` cache settings + code — restart to pick up
`.env` or code changes.

## Current status: PHASES 0–14 COMPLETE — proactive discovery + one-command dev + many languages

This session built the two optional post-12 phases and broadened the language coverage.

**Phase 13 — Proactive bug discovery (`app/discovery/`).** Detectors emit cheap, noisy
`Candidate`s in the sandbox (`sources/`: `tests` = run-the-suite failing tests; `static` =
mypy/ruff; `diff` = untested churn hotspots), behind a `Detector` protocol + `ScanContext`.
`scan_repo` fans them out (per-detector errors swallowed); `triage` dedups (fingerprint = rule +
line-bucketed location + symbol), ranks (confidence × severity), and **budget-caps** promotions;
`promote.candidate_to_task` renders a candidate to issue text and **parses it back** into the same
`IssueTask` the webhook produces (render→parse round-trip — one code path). New `scan` + `finding`
tables (`finding.fingerprint` **unique per repo** → a re-scan never refiles) + migration
`a1b2c3d4e5f6` (also widens `job.trigger` VARCHAR for the new `discovery`/`scrape` values).
`app/db/discovery.py` persists scans/findings and `promote_candidate` files a `trigger="discovery"`
JOB through the **unchanged** pipeline. `bugfix-scan` CLI is spend-gated (`--confirm` to promote, like
eval). `/findings` + `/scans` API + a dashboard **Findings tab** (one-click promote = human gate at
discovery, §9). **Reproduction is the precision filter** — a candidate that won't go red is dropped
before any fix spend.

**Phase 14 — one-command local dev (`npm run dev`).** `app/db/bootstrap.py` (`bugfix-bootstrap`):
`--reset` truncates the job-history tables (children-first), **refusing unless `APP_ENV=local`**
(`ResetNotAllowed`); `--scrape` pulls open GitHub issues via the new read-only
`GitHubClient.list_open_issues` (reusing Phase 5 install-token auth) and enqueues each through the
**same** `ingest_labeled_issue` path (`trigger="scrape"`, capped by `SCRAPE_MAX_JOBS`). The reset +
scrape logic is injectable (fake `IssueSource`) and SQLite-tested. `frontend/package.json` `dev`
orchestrates (via `concurrently` + `wait-on`) compose → `alembic upgrade` → bootstrap → API + worker
+ Vite under one Ctrl-C; `predev` sequences the infra steps. New `SCRAPE_*` settings + `.env.example`
+ README Quickstart. The C1 human gate is unchanged — scraped jobs still stop at `awaiting_approval`.

**Phase 8 extension — many more language adapters.** New `app/runner/adapters/common.py`
(`BaseRegexAdapter`: exit-code + regex result parsing, shared `relativize`/`parse_frames_with`) backs
six new adapters — **Rust** (`cargo test`), **Ruby** (RSpec), **Java/Kotlin** (Maven + Gradle),
**.NET** (`dotnet test`), **PHP** (PHPUnit), **Elixir** (`mix test`) — each with detect/install/build/
parse_frames/parse_result, a sandbox image (`docker/sandbox.{rust,ruby,jvm,dotnet,php,elixir}.Dockerfile`),
and `Framework` enum members. Registered in the ordered registry (manifest-keyed, no detection
collisions). Allowlist `commands` widened to the new test toolchains (cargo/ruby/bundle/rspec/rake/
mvn/gradle/dotnet/php/phpunit/composer/mix) — but **not** git/curl/scanners: the discovery detectors
call the sandbox directly, so the agent never gains git/push reach (C5 lock test updated to match).

Acceptance — all offline: `tests/integration/test_discovery_acceptance.py` (scan → promote → reproduce
→ verify green → `awaiting_approval`; re-scan dedups), `tests/unit/test_discovery_{finding,triage,scan}.py`,
`tests/unit/test_api_findings.py`, `tests/unit/test_db_bootstrap.py`, `tests/unit/test_adapter_extra.py`,
`frontend/src/__tests__/FindingsList.test.tsx`. Whole offline Python suite: **336 passed, 1 skipped**
(integration deselected; the one env-sensitive `test_vcs_auth` case passes when `.env` has no GitHub
creds — it's green in CI). ruff + format + mypy clean; `alembic check` drift-free. Frontend: **14
vitest tests** pass, `tsc` clean. New Python runtime deps: none; new frontend dev deps: `concurrently`,
`wait-on`.

**Next session:** **Phase 15 (Deploy + CI/CD)** — dockerize all services, Fly.io with managed Postgres
+ Redis + secrets, GitHub Actions test→build→push→deploy, migrations on deploy, healthchecks, rollback;
the deploy start must be **non-destructive** (migrations only — never `--reset`/auto-scrape). Then
**Phase 16 (docs + demo + final eval number)**. Discovery follow-ups: the runtime (Sentry/Datadog) and
LLM-review detector sources are stubbed out by design (cut #1) — add behind the same `Detector` protocol
if precision warrants; consider a scheduled nightly scan (cron) per repo.

---

## Earlier: PHASES 0–12 COMPLETE — React dashboard (watch live + approve)

Phase 12 (Dashboard) closes the loop: a human can watch a fix stream in and approve it from a
browser. It also lands the approve/reject wiring that was open since Phase 7 — the dashboard button
is its natural driver.

- **Backend — the C1 gate, now over HTTP (`app/api/jobs.py`):** `POST /jobs/{id}/approve` and
  `/reject` append an **immutable decision** and drive the state machine. Both are legal **only from
  `awaiting_approval`** — any other state is a 409 with no row written (the transition is checked
  *before* the write, and the request session rolls back on the raise). They never touch GitHub: the
  draft-PR publish stays behind `bugfix-pr open --confirm` (the decision chosen for this phase —
  record + transition only, no auto-publish, no surprise egress). `GET /jobs/{id}/artifacts/{kind}`
  serves the **diff / reasoning / trace** bodies the UI renders (`log` is SSE-only; `issue_body` is
  untrusted → both refused with 400).
- **Backend — DB approval store (`app/db/approvals.py`):** async `record_decision` / `latest_decision`
  over the Phase 6 `approval` table — the DB-backed, async counterpart of the Phase 5
  `app.vcs.approval` JSON/in-memory stores (append-only; a reversal is a new row; latest wins). Caller
  owns the transaction, mirroring `record_log`.
- **Backend — CORS (`app/api/main.py` + `cors_origins` setting):** the Vite dev server
  (`localhost:5173`) is a different origin, so `CORSMiddleware` allows the configured dev origins
  (GET/POST). Prod serves the built assets same-origin, so this is dev-only.
- **Frontend (`frontend/`, React 18 + Vite 5 + Tailwind 3 + TS):** `src/api.ts` (typed client, relative
  URLs → works behind the dev proxy and same-origin in prod, `ApiError` carries the server `detail`);
  `src/hooks/useJobStream.ts` (EventSource over the SSE log endpoint → collects `log` lines + the
  terminal `state` event); components `JobList`, `JobDetail` (status, per-phase runs, fix summary,
  **live log**, **diff view**, **reasoning trace**, and **approve/reject** — shown only when
  `awaiting_approval`, with an actor field), `StatusBadge`, `DiffView`; `App.tsx` (list + detail,
  polls the list every 4s as a coarse fallback while SSE carries per-job live logs). `vite.config.ts`
  proxies `/jobs|/metrics|/healthz` → `:8000` in dev.

Acceptance (Phase 12): **a fix can be watched live and approved from the UI** — the SSE hook streams
progress, the diff/reasoning artifacts render, and the approve button POSTs to the C1-gated endpoint.
Covered **offline**: backend over ASGI + SQLite (`tests/unit/test_api_approvals.py`,
`test_api_cors.py` — approve/reject record+transition, 409 on wrong state with no row, 404/400, defaults,
artifact fetch + disallowed-kind guard, CORS allow/deny); frontend via Vitest + jsdom
(`frontend/src/__tests__/` — api client URLs/methods/`ApiError`, `useJobStream` log+state collection,
`JobDetail` approve/reject/error/hidden-controls flows with mocked fetch + EventSource). Whole Python
suite: **305 passed, 4 skipped** offline (+9 integration deselected); ruff + format + mypy clean;
`alembic check` drift-free (the `approval` table already existed from Phase 6 → no migration). Frontend:
**12 vitest tests pass** and `npm run build` (tsc + vite) is green. New Python runtime deps: none
(`CORSMiddleware` ships with FastAPI). Frontend deps are isolated under `frontend/` (gitignored
`node_modules/` + `dist/`).

**Phase renumber (this session):** two new optional phases were inserted after Phase 12 (design
only): **Phase 13 — Proactive bug discovery** (`docs/PHASE13_BUG_DISCOVERY.md`) and **Phase 14 —
One-command local dev / `npm run dev`** (`docs/PHASE14_DEV_ORCHESTRATION.md`). Deploy is now
**Phase 15** and Docs is **Phase 16**. Both 13 and 14 are optional and off the critical path
(cut #0 / #0b).

**Next session:** **Phase 13 (Proactive bug discovery)** if pursuing it — `app/discovery/` sources +
`scan`/`finding` tables + `bugfix-scan` CLI, feeding synthetic `IssueTask`s into the existing flow;
reproduction is the false-positive filter. **Phase 14 (one-command `npm run dev`)** is the other
optional add — compose + uv API/worker + Vite under one command, with a `bugfix-bootstrap` that
wipes the dev DB then scrapes open GitHub issues into the pipeline on startup (dev-only, gated by
`APP_ENV=local` + `SCRAPE_MAX_JOBS`). Otherwise skip to **Phase 15 (Deploy + CI/CD)** — dockerize
all services, Fly.io with managed Postgres + Redis + secrets, GitHub Actions
test→build→push→deploy, migrations on deploy, healthchecks, rollback; serve `frontend/dist`
same-origin from the API. Still optional: auto-publish on approve (wire `open_draft_pr_for_fix`
behind the approve endpoint once GitHub creds live in the API process — crosses a stop-and-ask
gate), and a real SWE-bench-lite number.

---

## Earlier: PHASES 0–11 COMPLETE — eval harness (headline resolve rate)

Phase 11 (Eval harness) turns the Phase 4 `solve_issue` pipeline into a measurable benchmark: a *suite*
of buggy cases, each run end-to-end, scored with the **same `app.telemetry.metrics`** the live fleet
uses. One command (`bugfix-eval run`) prints the headline resolve rate.

- **`eval/dataset.py`:** `EvalCase` value object (id, issue text, a way to materialize a fresh
  workspace) + `load_suite`. The shipped **custom** suite lives at `eval/data/<suite>/<case>/` as
  `meta.json` + `issue.md` + `workspace/`. `EvalCase.materialize` writes inline `files`, or defers to
  a `setup` callable (the seam the SWE-bench clone path uses) — so both dataset sources run one path.
- **`eval/harness.py`:** `run_case` materializes a case → runs `solve_issue` → distills a `CaseResult`
  (resolved / edited / cost_usd via `cost.cost_usd` / duration). Every failure (materialize/clone,
  sandbox, model) is caught and recorded as a non-resolved result so **one bad case never aborts the
  suite**. Client, sandbox, and clock are injected → the whole harness runs offline against a scripted
  fake + `LocalSandbox`. `run_suite` streams a `progress` callback per case.
- **`eval/score.py`:** maps `CaseResult` → `metrics.JobOutcome` and calls the fleet's `compute_metrics`
  (so eval numbers == fleet numbers). `EvalReport` (headline + per-case), `save_report`/`load_report`,
  and `score_delta(prev, cur)` — the **tuning loop**: run, tweak retry budget / localization / prompts,
  re-run, diff the recorded scores. `prev` accepts a stored report's `metrics` dict.
- **`eval/swebench.py`:** SWE-bench-lite loader, **gated behind the dataset + network** (like the
  Phase 5/8 acceptance). `load_instances` parses a JSONL offline; `materialize_instance` clones the
  repo at `base_commit` + applies the instance `test_patch` (git injected → fakeable). `bugfix-eval
  run --suite swebench-lite --jsonl <path>` wires it. Not run in CI.
- **`eval/cli.py`:** `bugfix-eval list|run`. A real run **costs tokens** → the build-plan stop-and-ask
  gate is enforced in code: `run` refuses without `--confirm` (and without `ANTHROPIC_API_KEY`).
  `--out` saves a report; `--compare` diffs against a saved one. Registered as the `bugfix-eval` script;
  `eval` added to the wheel packages; `eval/data` ruff-excluded (intentionally-buggy fixtures).

Acceptance (Phase 11): **single command runs the eval and prints the headline resolve rate.** Verified
on the **real Anthropic API** — `bugfix-eval run --suite custom --confirm` scored
**resolve rate 100.0% (3/3)**, regression 0.0%, mean time-to-fix 33.2s, cost-per-fix $0.069, total spend
**$0.208** on `claude-sonnet-4-6` (baseline saved to `eval/results/phase11-baseline.json`).
Offline-covered: dataset loader, harness (resolve + injected-clock duration + error-degradation +
progress), scoring + deltas, SWE-bench parse + fake-git materialize, CLI list + spend/key/jsonl gates
(`tests/unit/test_eval_*.py`); the real-API headline is `tests/integration/test_eval_acceptance.py`
(marked `integration`). Whole suite: **292 passed, 4 skipped** offline (+9 integration deselected);
ruff + format + mypy clean; `alembic check` drift-free (Phase 11 added no schema). New runtime deps: none.

**Next session:** Phase 12 (React dashboard) — list runs, run detail + diff + reasoning trace, live SSE
status, approve/reject wired to the human gate. Still open from Phase 7: migrate the APPROVAL store off
the JSON file onto the `approval` table behind the same `ApprovalStore` protocol, and wire
approve/reject endpoints + the Phase 5 publish path at the `awaiting_approval` gate (the dashboard's
approve button is the natural driver). For a *real* SWE-bench-lite number, export the
`princeton-nlp/SWE-bench_Lite` split to JSONL and run `bugfix-eval run --suite swebench-lite` at cost.

---

## Earlier: PHASES 0–10 COMPLETE — observability + cost accounting

Phase 10 (Observability + cost) makes any past run reconstructable and reports cost per job. It
also fixes a Phase 9 CI regression first (see below).

- **Phase 9 CI fix (`app/sandbox/docker.py`):** the three live-container red-team checks in
  `test_c2_sandbox.py` were gated on `docker_available()` — which only checks the `docker` CLI is on
  PATH. CI has the CLI but never builds `bugfix-sandbox:latest`, so the tests *ran* under
  `pytest -m "not integration"` and failed with exit 125 ("Unable to find image"). Added
  `image_available(image)` (`docker image inspect`) and re-gated the live tests on it, so they skip
  cleanly without a built image and still run where it exists. Unit-covered (`test_sandbox_image.py`).
- **Cost accounting (`app/telemetry/cost.py`):** a per-model price table ($/Mtok in+out) →
  `cost_usd(model, in, out)` and `cost_breakdown(...)`. Resolves a context suffix (`claude-opus-4-8[1m]`
  → base price); unknown model costs `0.0`. The pipeline now writes the full breakdown (incl.
  `cost_usd`) onto `job.cost`, surfaced as `cost_usd` on the job API view.
- **Tracing (`app/telemetry/tracing.py`):** `build_trace(result, model=…)` distills a `SolveResult`
  into a JSON, **secret-free** (Phase-9 `scrub` over every string) record of the run — every tool call
  (name/args/result), plan, localization, token usage, and USD cost. Persisted as a new
  `ArtifactKind.TRACE` artifact → **a run is reconstructable offline, no model re-run, no Langfuse**.
  A `Tracer` protocol mirrors it to Langfuse (`LangfuseTracer`, lazy SDK import) and returns the trace
  id (stamped on the verify `Run.langfuse_trace_id`); `get_tracer(settings)` returns a `NullTracer`
  when keys/SDK are absent (the offline default). New optional extra `observability = [langfuse]`.
- **Metrics (`app/telemetry/metrics.py` + `app/api/metrics.py`):** pure aggregation over `JobOutcome`
  value objects → resolve rate, regression rate (edited-but-unresolved / edited), mean time-to-fix
  (resolved only), cost-per-fix, total spend. `GET /metrics` maps ORM rows (Job+Fix+cost+timestamps)
  onto it. Unit + ASGI-over-SQLite covered.

Acceptance (Phase 10): cost per job reported (`job.cost.cost_usd`, `/metrics`); any past run
reconstructable from the TRACE artifact (+ existing diff/reasoning artifacts) without re-running the
model. New code is injectable + offline-testable (recording fake tracer in the pipeline test). Whole
suite: **270 passed, 4 skipped** offline (+8 integration deselected); ruff + format + mypy clean;
`alembic check` drift-free (TRACE is a VARCHAR enum value → no DDL). New runtime deps: none (langfuse
is an optional extra).

**Next session:** Phase 11 (Eval harness) — SWE-bench-lite + custom buggy-commit set, resolve-rate +
regression-rate scoring (reuse `app.telemetry.metrics`), one command prints the headline number.
Still open from Phase 7: migrate the APPROVAL store off the JSON file onto the `approval` table behind
the same `ApprovalStore` protocol, and wire approve/reject endpoints + the Phase 5 publish path at the
`awaiting_approval` gate.

---

## Earlier: PHASES 0–9 COMPLETE — security hardened + red-team suite ⭐

Phase 9 (Security hardening, never cut) proves the five non-negotiable constraints C1–C5 against
adversarial inputs and closes the one outstanding hardening gap:

- **C4 redaction filter (new code):** `app/telemetry/redaction.py` — a structlog processor
  (`redact_processor`) that scrubs GitHub token families (`ghp_/gho_/ghu_/ghs_/ghr_`), fine-grained
  PATs (`github_pat_*`), JWTs (the signed App JWT), and inline `Authorization`/`Bearer`/`token=`
  header values out of **every** log event, plus value-level redaction for sensitive-named keys
  (token/secret/password/api_key/…). Recurses into nested dict/list payloads. Wired into
  `configure_logging` just before the renderer. The reusable `scrub(text)` is what the suite uses to
  assert a run's trace carries no token. This was the only control SECURITY.md named that wasn't yet
  in code; C1/C2/C3/C5 were already enforced by Phases 2–8 — Phase 9 is their adversarial proof.
- **Red-team suite (`tests/redteam/`, marker `redteam`):** dedicated package, `EVIDENCE.md` maps
  SECURITY.md §5 categories 1–7 → tests. **62 tests, all green offline** (the 3 live-container checks
  also carry `@pytest.mark.docker` and skip without a daemon; they ran + passed here — Docker present).
  - **C1 (`test_c1_human_gate.py`):** no-approval refused before any token mint; rejected decision
    refused; `draft=true` enforced (asserted against the real `GitHubClient` via an httpx
    `MockTransport` capturing the `/pulls` body); static scan of `app/vcs` for merge / `/merges` /
    `draft=False` / `--force` → none; the only `"/pulls"` POST in the tree is `github.py`.
  - **C2 (`test_c2_sandbox.py`):** construction-time proof of the `docker run` flags (`--network none`,
    `--cap-drop ALL`, `no-new-privileges`, `--read-only`, non-root `10001`, `--pids-limit`, mem cap +
    swap off, `--rm`, single workspace bind); deployed env refuses the local fallback; **live** egress
    blocked, rootfs read-only, fork-bomb contained by the PID cap.
  - **C3 (`test_c3_prompt_injection.py`):** an injection corpus + the malicious argv an obedient agent
    would emit → every one refused by the allowlist; a compliant scripted model that tries `git push`
    mid-`solve_issue` is contained (the call is `is_error`); static proof the execution plane
    (`agent`/`runner`/`sandbox`/`index`) never imports `app.vcs`.
  - **C4 (`test_c4_secret_isolation.py`):** `InstallationToken` repr/str redaction; `scrub` over each
    token family + auth header (and leaves ordinary text alone); the processor scrubs keys + embedded
    secrets + nested payloads; **end-to-end** log scrub via `configure_logging` + `capsys`; auth errors
    echo no token; the model context assembled across a full `solve_issue` run carries no secret.
  - **C5 (`test_c5_allowlist.py`):** unknown tool, disallowed commands (git/curl/wget/nc/bash/sh/rm/…),
    empty argv, path traversal on read+edit, and an argument-shape fuzz set → all default-denied; the
    command set is pinned so an accidental widening fails the test.

Whole suite: **249 passed, 1 skipped** offline (+8 integration deselected); ruff + format + mypy
clean; `alembic check` drift-free (Phase 9 added no schema). New runtime deps: none.

**Next session:** Phase 10 (Observability + cost) — structlog is already redaction-safe; add Langfuse
tracing + cost accounting + metrics. Still open from Phase 7: migrate the APPROVAL store off the JSON
file onto the `approval` table behind the same `ApprovalStore` protocol, and wire approve/reject
endpoints + the Phase 5 publish path at the `awaiting_approval` gate.

---

## Earlier: PHASES 0–8 COMPLETE — multi-language (Python, JS/TS, Go)

Phase 8 (Multi-language adapters) generalizes the runner beyond pytest behind a plugin layer:

- `app/runner/adapters/base.py` — the **`LanguageAdapter`** contract: `detect`, `install_command`,
  `build_command`, `parse_frames`, `parse_result`, plus `framework` / `image` / `commands`. Each
  adapter decides *what* to run and *how* to read output; execution stays the sandbox's job.
- `app/runner/adapters/{python,javascript,golang}.py` — three adapters. **PytestAdapter** is a thin
  facade over the original Phase 2 modules (no logic duplicated). **NodeTestAdapter** drives
  `node --test --test-reporter=tap` (zero-dep; TAP forced so parsing is deterministic off-TTY) and
  parses the `# pass/fail` footer + `not ok` YAML blocks (inline *and* block-scalar `error:`),
  ignoring `node:internal/*` frames. **GoTestAdapter** drives `go test ./... -v`, counts
  `--- PASS/FAIL`, reads `file.go:line: msg` logs + panic stacks, and maps a non-zero exit with no
  failures to a compile ERROR.
- `app/runner/adapters/__init__.py` — ordered **registry** (Python first → existing behavior
  unchanged); `detect_adapter`, `adapter_for`, `parse_any_frames` (used by issue parsing, which sees
  text before any workspace).
- `app/runner/run.py` — generic **`run_tests`**: detect adapter → (optional `install`) → build → run
  in sandbox → `parse_result`. Shares the single `NoTestFramework`. `detect.py`'s `detect_framework`
  now delegates to the registry; `run_pytest`/`parse_result` kept for back-compat.
- **Seams wired**: `ToolExecutor._run_tests` → `run_tests`; allowlist `commands` +=
  `node/npm/npx/go/pip`; `solve_issue` selects the per-language sandbox image via `detect_adapter` +
  `get_sandbox(image=…)` (local fallback ignores it). `docker/sandbox.{python,node,go}.Dockerfile`
  carry each toolchain.

Acceptance (Phase 8): a **verified red→fix→green** run in each of Python, JS/TS, Go via the real
runner + LocalSandbox (`tests/integration/test_multilang_acceptance.py`; JS/Go skip when the host
toolchain is absent, like the PR acceptance skips without creds). Adapters are unit-covered offline
against captured `node --test` TAP + `go test -v` output (`test_adapter_node.py`,
`test_adapter_go.py`, `test_adapters.py`). Whole suite: **192 passed, 4 skipped** offline; ruff +
format + mypy clean; `alembic check` drift-free (Phase 8 added no schema). New runtime deps: none
(Node/Go toolchains live in the sandbox images, not the Python project).

**Toolchain follow-up (this session):** Node (v26.3.1) and Go (1.26.4) are now installed on the dev
host, so the two `@skipif(which(...) is None)` JS/Go acceptance cases in
`test_multilang_acceptance.py` no longer skip — all three languages run red→fix→green via the real
runner + LocalSandbox. Full suite now **193 passed, 3 skipped** (the remaining 3 are the
GitHub-credential-gated real-PR acceptance and the intentional docker-present `test_sandbox_local`
skip — none are language adapters).

**Next session:** Phase 9 (Security hardening ⭐ never cut) — see the build plan. Still open from
Phase 7: migrate the APPROVAL store off the JSON file onto the `approval` table behind the same
`ApprovalStore` protocol, and wire approve/reject endpoints + the Phase 5 publish path at the
`awaiting_approval` gate. For the *real* multi-language acceptance, build the node/go sandbox images
(and optionally install go locally to un-skip `test_go_verified_fix`).

---

## Earlier: PHASES 0–7 COMPLETE — fire-and-forget workers, pollable, crash-recoverable

Phase 7 (Async workers) drains the queue and drives the lifecycle:

- `app/workers/state.py` — the **job state machine**. `ALLOWED_TRANSITIONS` is the single source of
  truth (`queued → running → awaiting_approval → approved → done`, plus `failed`; `running → queued`
  for recovery; `awaiting_approval → rejected`). `transition(job, to, reason=…)` refuses illegal
  moves (`InvalidTransition`) and records/clears `failure_reason`. `LIVE_STATES`/`TERMINAL_STATES`.
- `app/workers/queue.py` — `JobQueue` over an arq Redis pool; `enqueue` is **deduped by job id**
  (`_job_id="job:<uuid>"`, so a duplicate webhook or a re-enqueue collapses to one task).
  `create_job_queue` returns `None` when `redis_url` is unset → callers skip enqueuing (offline).
- `app/workers/pipeline.py` — `run_pipeline(db, job_id, …)`: claims a **queued** job (`→ running`,
  durable so a crash is visible), clones into an **isolated per-job workspace**
  (`workspace_root/<job_id>`, re-entrant — wiped + re-cloned on replay), runs Phase 4 `solve_issue`
  in the sandbox (off the event loop via `asyncio.to_thread`), persists RUN (localize/fix/verify) +
  diff/reasoning ARTIFACT + FIX rows + `job.cost`, then routes: resolved → **awaiting_approval**
  (human gate, never auto-published — C1); unresolved/any error → **failed** (reason recorded, no
  tight retry). Every seam (model client, clone, sandbox, `solve`) is injected → fully offline.
- `app/workers/recovery.py` — `recover_stuck_jobs`: on worker startup, resets `running` jobs to
  `queued` (legal edge) and returns ids to re-enqueue. Idempotent. **This is the crash-recovery.**
- `app/workers/worker.py` — arq `WorkerSettings` (`run_job` task, `on_startup` = configure + open
  DB/queue + recovery sweep + re-enqueue, `on_shutdown` = close, `max_jobs=4`, `job_timeout=1800`).
  `bugfix-worker` console script; or `arq app.workers.worker.WorkerSettings`.
- `app/api/jobs.py` — read-only `GET /jobs`, `GET /jobs/{id}` (state + cost + per-phase runs + fix
  summary), `GET /jobs/{id}/logs` (**SSE** — replays `LOG` artifacts then tails, closes at terminal
  / awaiting_approval; tracks seen ids so ties in second-granular `created_at` never dup/drop).
- Wiring: `app/api/main.py` lifespan opens/closes the queue; the **webhook now enqueues** after
  ingest (commits first so the worker sees the row; enqueue is a no-op when no queue). Progress is
  persisted as coarse `LOG` artifacts (`app/workers/progress.py`) so status reads need no Redis.

Acceptance (Phase 7): fire-and-forget (webhook enqueues; worker drains), pollable status
(`/jobs/{id}` + SSE logs), recoverable on crash (`recover_stuck_jobs`). Covered **offline** —
`tests/unit/test_worker_{state,recovery,pipeline}.py` + `test_api_jobs.py` (pipeline runs the real
LocalSandbox + a scripted client end to end to the human gate; unresolved/clone-error → failed;
non-queued replay is skipped). Whole suite: **160 passed, 1 skipped** offline; ruff + format + mypy
clean; `alembic check` drift-free (Phase 7 added no schema). New dep: `arq>=0.26` (pulls redis).

**Next session:** Phase 8 (JS/TS + Go adapters) — generalize detect/runner/trace beyond pytest.
The APPROVAL store can still migrate from the JSON file onto the `approval` table behind the same
`ApprovalStore` protocol; the worker's human-gate hand-off (`awaiting_approval`) is the natural
place to wire approve/reject endpoints + the Phase 5 publish path (the only remaining remote write).

---

## Earlier: PHASES 0–6 COMPLETE — webhook → queued job, persisted

Phase 6 (Backend API + data model + webhook) lands the trusted control plane:

- `app/models/` — SQLAlchemy 2.0 models for repos/jobs/runs/artifacts/fixes/approvals/code-chunks
  (mirrors DATA_MODEL.md). `base.py` keeps types **dialect-portable** (`Uuid`; `JSON`+JSONB
  variant; non-native VARCHAR enums) so the same schema runs on Postgres *and* the SQLite unit
  DB — no Postgres server needed for tests.
- `migrations/` — Alembic from day one. `alembic upgrade head` applies the initial schema;
  `alembic check` is drift-free. URL comes from `Settings`, not `alembic.ini`. Versions are
  ruff-excluded (autogenerated).
- `app/db/session.py` — async engine + sessionmaker (`Database`), with a commit/rollback session
  scope; coerces sync URLs to async drivers.
- `app/db/jobs.py` — `ingest_labeled_issue`: the webhook's only write path. Upserts the repo,
  stores the **untrusted issue body as an ARTIFACT** (`issue_body_ref`, never inline), enqueues
  one **queued** JOB. **Idempotent** per live job (queued/running/awaiting) → duplicate
  deliveries return the existing job.
- `app/api/` — FastAPI app (`main.create_app`/`app`), `/healthz`, and `POST /webhooks/github`.
  `security.py` does **constant-time HMAC-SHA256** verification of `X-Hub-Signature-256`; a bad
  signature is a 401 and nothing is enqueued. Only `issues.labeled` with the `autofix` label
  enqueues; everything else is acknowledged + ignored. `bugfix-api` console script.

Acceptance (Phase 6): "labeling an issue creates a queued job row via webhook" — covered
**offline** over an ASGI transport + SQLite in `tests/unit/test_webhook.py` (plus bad-signature,
wrong-event, wrong-label, idempotency, health). Whole suite: 144 passed, 1 skipped offline; ruff
+ mypy clean. New deps: `fastapi`, `uvicorn[standard]`, `sqlalchemy[asyncio]`, `alembic`,
`psycopg[binary]` (sync Alembic + async app from one URL); dev `aiosqlite`, `pytest-asyncio`.

**Next session:** Phase 7 (arq workers + state machine) — drain queued jobs, run the
reproduce→fix→verify pipeline one container per job, transition queued→running→awaiting_approval
→done/failed, crash-recoverable. The APPROVAL store can also migrate from the JSON file
(`app/vcs/approval.py`) onto the new `approval` table behind the same `ApprovalStore` protocol.

---

## Earlier: Phase 5 — verified patch → human-gated draft PR ⭐

Phase 5 (GitHub integration, never cut) adds the **remote-write plane** in `app/vcs`, the sole
owner of GitHub mutations:

- `approval.py` — the **C1 human gate**, persisted append-only (latest decision wins; a reversal
  is a new record). `assert_approved` is the single chokepoint; `InMemoryApprovalStore` (tests)
  and `JsonFileApprovalStore` (CLI, `./.bugfix/approvals.jsonl`) until Postgres lands in Phase 6.
- `auth.py` — GitHub App **RS256 JWT → short-lived installation token** (C4). `InstallationToken`
  redacts its value in `repr`/`str`; `now` is injected so JWT signing is deterministic/testable.
- `github.py` — REST client with a **draft-PR-only** surface: Git Data API commit (blob→tree→
  commit→ref), `open_draft_pr` (always `draft=true`), `comment`. **No merge / push-to-base
  method exists** (asserted by a test).
- `publish.py` — `open_draft_pr_for_fix`, the **only remote write**: asserts approval *first*
  (no token minted otherwise), then mints-uses-discards the token, commits, opens the draft PR,
  posts the writeup as a comment. Store + minter injected → fully offline-testable.
- `bundle.py` — bridges a Phase 4 `SolveResult` → a credential-free `FixBundle`.
- `cli.py` — `bugfix-pr approve|reject|status|open`. `open` is **STOP-AND-ASK** (`--confirm`).

40 vcs unit tests (incl. the C1/C4 invariants); the real-PR acceptance is
`tests/integration/test_pr_acceptance.py`, skipped unless a disposable test repo + App creds are
in the env. Whole suite: 130 passed offline, ruff + mypy clean. New deps: `httpx`, `pyjwt[crypto]`.

**Next session:** Phase 6 (FastAPI + Postgres/Alembic + webhook) — move the APPROVAL store to a
real `approvals` table behind the same `ApprovalStore` protocol, and wire the webhook→job path.
Before the first *real* PR: create + install the GitHub App on a test repo, set the env vars, run
the integration acceptance.

---

## Earlier: PHASES 0–4 COMPLETE — issue text → verified patch + writeup ⭐

Phases 0–4 are built, tested, and lint/type-clean. On top of the Phase 3 agent loop, Phase 4
(the core milestone, never cut) takes **raw issue text or a stack trace** and produces a
**verified patch plus a reasoning writeup**: it parses the issue, ranks suspect files, drives
the agent to reproduce (writing a failing test if none exists), fix, and self-correct, enforces
edit guardrails, and assembles a Markdown writeup. Verified against the real API on two
scenarios (source-only bug → agent authors a reproduction test; traceback issue → localize +
fix). Next: Phase 5 (GitHub integration — human-gated draft PR; **STOP-AND-ASK before the first
real PR**).

### Session 5 (2026-06-30) — Phase 4: issue → reproduce → localize → fix → explain ⭐

- **`app/agent/issue.py`:** `IssueTask` + `parse_issue` — lexical distillation of issue text /
  stack traces into `{title, body, error_type, error_message, frames, referenced_paths,
  test_nodeids, identifiers}`. Reuses the Phase 2 `parse_frames`; never invents an exception when
  there's no traceback. `to_prompt()` renders the signals for the agent.
- **`app/agent/localize.py`:** `Suspect` + `rank_suspects(brain, task)` — fuses traceback frames
  (innermost weighted highest), existing referenced paths, and identifier→symbol-definition
  files; test files penalized so source ranks above tests. Deterministic, capped at `limit`.
- **`app/agent/guardrails.py`:** `sensitive_reason(path)` classifies CI config / lockfiles /
  secrets (by path, not content); `check_diff_budget` caps cumulative changed lines
  (`DEFAULT_MAX_DIFF_LINES=200`). Wired into `ToolExecutor._edit_file`: a sensitive edit is
  **refused and recorded as a flag** (returned to the model as an error), and an over-budget edit
  is applied-then-rolled-back (`_rollback`) and refused. `ToolExecutor` gained `flags` +
  `max_diff_lines`.
- **`app/agent/writeup.py`:** `change_summary(edits)` (files / +insertions / -deletions, pure)
  and `build_writeup(task, suspects, result, flags)` — deterministic Markdown (issue, localization,
  root-cause, embedded ```diff, verification verdict, guardrail flags). No extra model call.
- **`app/agent/solve.py`:** `solve_issue(...)` orchestrator → `SolveResult` (task, suspects,
  agent, flags, writeup, summary). A test node id in the issue scopes the authoritative
  verification; otherwise the whole suite runs (so a freshly written reproduction test counts).
  Model client injected (offline-testable). `prompts.py` gained a reproduce-first rule + the
  guardrail rule + `build_solve_prompt`.
- **CLI:** `bugfix-agent solve <ws> --issue/--issue-file [--writeup-out] [--local]`.
  - **Acceptance ✅:** `tests/integration/test_solve_acceptance.py` (marked `integration`) — two
    real-API scenarios pass: (1) `source_only_bug` (no test) → agent writes a reproduction test,
    fixes `titleize`, RESOLVED; (2) traceback issue → `calc.py` ranked first, fixed, RESOLVED.
    Ran in ~263s on the local sandbox.
  - **Offline tests:** issue parser, localizer, guardrails (sensitive paths + diff budget),
    executor guardrail enforcement, writeup/change-summary, the `solve` orchestrator (scripted
    fake client + real LocalSandbox), and CLI smoke tests. Full offline suite: **105 passed, 1
    skipped**; ruff + format + mypy clean.
  - **Gotcha:** `str.lstrip("./")` strips leading dots/slashes as a *char set*, not a prefix — it
    turned `.github/...`/`.env` into `github/...`/`env` and broke sensitive-path detection; use an
    explicit `"./"` prefix strip. Guardrail rollback relies on `apply_edit` only ever producing an
    empty `before` for a newly-created file (so empty-before ⟺ safe to unlink).

### Session 4 (2026-06-30) — Phase 3: agent loop (core)

- **`app/agent`:** `models.py` (`AgentBudget` = iterations/token/time ceilings, `AgentResult`,
  `ToolCall`, `FileEdit`, `TokenUsage`, `StopReason`); `edit.py` (`apply_edit` — unique-match
  str-replace confined to the workspace via the Phase 1 traversal guard, empty `old_str` creates
  a file; `unified_diff` coalesces multiple edits to the same file into one net diff);
  `tools.py` (six Anthropic tool schemas + `ToolExecutor` wrapping `RepoBrain`/sandbox/edit, with
  **`Allowlist.check_tool` enforced before every dispatch** and `check_command` gating
  `run_command`; tool errors are returned to the model with `is_error=True`, never raised; results
  capped at 8k chars); `prompts.py` (system prompt + planning prompt + task builder); `loop.py`
  (`AgentLoop` — manual tool-use loop, **not** the SDK runner, so the allowlist gates dispatch and
  the budget is enforced turn-by-turn; planning step, `thinking={"type":"adaptive"}` +
  `output_config={"effort":"high"}`, `pause_turn`/`refusal` handling, early-stop when the model's
  own run is green, then an **authoritative final `run_pytest` verification** decides `resolved`);
  `client.py` (`make_create_message` factory — injects `anthropic.Anthropic().messages.create`;
  key from settings, never logged); `cli.py` (`bugfix-agent fix` Typer command).
- **Deps/wiring:** `anthropic==0.113.0` moved into core deps (was the optional `agent` extra);
  `bugfix-agent` script registered in `pyproject`.
  - **Acceptance ✅:** `tests/integration/test_agent_acceptance.py` (marked `integration`, skips
    without `ANTHROPIC_API_KEY`) — agent fixes a one-line factorial off-by-one and the target test
    goes green. Verified against the real API. Also confirmed the `bugfix-agent fix` CLI end-to-end
    on a separate `average()` bug (diff produced, `RESOLVED`).
  - **Offline tests:** scripted-fake-client loop tests (planning, tool dispatch, edit application,
    stop-reason handling, iteration budget, token accounting), tool dispatcher + allowlist tests
    (real `RepoBrain`/`LocalSandbox`, no API/Docker), and edit/diff tests. Full offline suite:
    62 passed, 1 skipped; ruff + mypy clean.
  - **Gotcha:** a single-command Typer app collapses the subcommand name, so a `@app.callback()`
    no-op is added to keep `bugfix-agent fix` explicit (matches `bugfix-run`). The model sometimes
    emits pseudo `<tool_call>` text *inside* the planning turn — harmless narration; real tool
    calls only go through the loop's tool-use blocks.
  - **Note (egress):** the agent loop makes real Anthropic API calls — the first deliberate
    network egress in the project. The acceptance run is one small fix; keep `integration` runs
    intentional (they cost tokens).

### Session 3 (2026-06-30) — Phase 2: test runner + sandbox v1

- **`app/sandbox`:** `ResourceLimits` (cpus/memory/pids/timeout, **network off by default**) +
  `ExecResult`. `Sandbox` Protocol with `run()` + `mount_point()`. `DockerSandbox` — one
  `docker run` per command: `--rm`, `--network none`, `--cpus/--memory/--memory-swap/--pids-limit`,
  `--cap-drop ALL`, `--security-opt no-new-privileges`, `--read-only` + `--tmpfs /tmp`,
  non-root `10001`, single `/workspace` bind mount; named container force-killed on wall-clock
  timeout (via `docker` CLI subprocess — no SDK dep, matches `clone.py`). `LocalSandbox` —
  dev-only subprocess fallback (timeout + best-effort POSIX rlimits). `get_sandbox()` picks
  Docker when present, **refuses the local fallback in deployed envs**.
- **`app/runner`:** `detect_framework` (pytest via config tables / `pytest.ini` / `conftest.py` /
  `test_*.py`, skipping vendored dirs); runs `pytest -q --tb=native -rfE -p no:cacheprovider`;
  `trace.parse_frames` pulls `File "...", line N, in func` frames from native tracebacks;
  `parse.build_failures` stitches summary counts + short-summary node ids + per-failure frames,
  **filtering to in-workspace frames** (drops pytest/pluggy/stdlib noise) by relativizing against
  the sandbox's `mount_point` (`/workspace` for Docker, host path for local). `run_pytest` ties
  detect → execute → parse. `bugfix-run` Typer CLI (`detect` / `test`, `--local` flag).
- **Image:** `docker/sandbox.Dockerfile` now installs `pytest>=8.2`. Build:
  `docker build -t bugfix-sandbox:latest -f docker/sandbox.Dockerfile .`
  - **Acceptance ✅:** known-failing project → `FAILED 1 passed, 2 failed` with frames
    `test_calc.py:N → calc.py:N in divide`. Verified both via `LocalSandbox` (offline unit test)
    and the real Docker container (integration, marked `docker`). A no-egress test confirms the
    container can't open a network socket. Full suite: 45 passed, 1 skipped; ruff + mypy clean.
  - **Gotcha:** `--tb=native` includes the full pytest/pluggy frame stack; the in-workspace
    filter is what isolates the user's code. When captured/narrow, pytest's summary line has **no
    `=` decoration** (`2 failed, 1 passed in 0.01s`) — `parse_counts` keys on the `in <n>s`
    duration, not the banners.
  - New pytest marker `docker` (deselect with `-m 'not docker'`); needs the image + Docker.

### Session 2 (2026-06-30) — what got built

- **Phase 0 scaffold:** target layout under `app/{api,agent,vcs,sandbox,index,runner,workers,
  models,core,telemetry}` + `frontend/ eval/ docker/ deploy/ tests/`. `pyproject.toml`
  (Python **3.12**, hatchling), ruff + mypy (strict) + pytest config, `.pre-commit-config.yaml`,
  `.env.example` (no secrets), `docker-compose.yml` (pgvector + redis), `docker/sandbox.Dockerfile`,
  CI stub `.github/workflows/ci.yml` (uv → lint → format → mypy → unit tests). Typed stubs with
  docstrings for every package; `app/core` has real `Settings` (pydantic-settings, SecretStr) +
  `Allowlist` primitive; `app/telemetry` has structlog setup.
  - **Acceptance ✅:** `pytest` runs, `ruff check`, `ruff format --check`, `mypy app` all pass.
- **Phase 1 repo brain (`app/index`):** `clone_repo` (git, shallow, URL or local path);
  `SymbolIndex` (tree-sitter Python: functions/methods/classes w/ locations + class parent);
  `search` (ripgrep `--json`, **pure-Python fallback** when `rg` absent); `read_file`
  (path-traversal-safe); `RepoBrain` facade with `find_symbol` = exact defs (tree-sitter) ∪
  usages (ripgrep word-search), vector backend consulted only as fallback (Protocol, no impl yet
  — needs Postgres); `repo-brain` Typer CLI (`clone`/`where`/`search`/`read`).
  - **Acceptance ✅:** `repo-brain where ./workspaces/cachetools LRUCache` → defined at
    `src/cachetools/__init__.py:280` + 49 usages. Integration test clones `tkem/cachetools` and
    asserts the lookup (`pytest -m integration`).

### Environment notes for next session

- Build/dev uses a **uv-managed Python 3.12** venv (`uv sync --dev`), **not** conda `the_env`
  (uv pins the exact 3.12 target the build plan requires and matches CI). Run tools via `uv run`.
- **ripgrep gotcha:** the shell's `rg` is a Claude Code *function*, not a binary; there was no
  real `rg` on PATH. Installed via `brew install ripgrep` (now at `/opt/homebrew/bin/rg`,
  v15.1.0). `uv run` only sees it with `/opt/homebrew/bin` on PATH. The Python fallback means the
  repo brain still works without it, but install rg for the fast path.
- `psf/cachetools` does NOT exist — the repo is `tkem/cachetools`. Used in the integration test.

### Original session (design baseline)

Session scope chosen by Parv: **plan & architecture only**. Docker + Anthropic API key to be
provided by Parv before any execution-dependent code is built.

## What's done

- [x] Scope + environment alignment (sandbox has Python 3.10, Node 22, ripgrep, git; **no
      Docker**, **no Anthropic key** in this sandbox).
- [x] `docs/ARCHITECTURE.md` — system context, component responsibilities, control/execution
      plane split, agent + sandbox model, deployment topology, open decisions.
- [x] `docs/DATA_MODEL.md` — entities (repos, jobs, runs, artifacts, fixes, approvals + code
      chunks), ERD, job state machine, invariants, indexes, migrations approach.
- [x] `docs/SEQUENCE_DIAGRAMS.md` — webhook→job, worker pipeline, human gate→draft PR, live SSE.
- [x] `docs/SECURITY.md` — threat model, trust boundaries, the 5 constraints mapped to controls
      + tests, red-team suite plan, residual risks.
- [x] `docs/BUILD_PLAN.md` — phases 0–16 with goals/deliverables/acceptance/deps/size/risk,
      dependency graph, critical path, cut-order, stop-and-ask gates.
- [x] `docs/README.md` — index of the above.

## What's left (the actual build)

Nothing in `app/`, `frontend/`, `eval/`, `docker/`, or `deploy/` exists yet. Build order and
acceptance tests are in `docs/BUILD_PLAN.md`. Phases not started:

- [x] Phase 0 — project scaffold (target layout, pyproject 3.12, lint/type/test, compose, CI stub)
- [x] Phase 1 — repo brain (clone, tree-sitter index, read_file/search/find_symbol; pgvector
      deferred — interface only, needs Postgres)
- [x] Phase 2 — test runner + sandbox v1 (pytest detect, capped Docker container, native-tb
      frame parser; local subprocess fallback; `bugfix-run` CLI)
- [x] Phase 3 — agent loop (Anthropic tool-use loop; allowlisted tools; planning + budget;
      `bugfix-agent` CLI; turns a known failing test green)
- [x] Phase 4 — issue→reproduce→localize→fix→explain ⭐ core milestone (issue.py / localize.py /
      guardrails.py / writeup.py / solve.py + `bugfix-agent solve`; acceptance verified on real API)
- [x] Phase 5 — GitHub integration, human-gated draft PR ⭐
- [x] Phase 6 — FastAPI + Postgres/Alembic + webhook
- [x] Phase 7 — arq workers + state machine (queue dedup, pipeline → human gate, crash recovery,
      `/jobs` status + SSE logs; `bugfix-worker`; 160 passed offline)
- [x] Phase 8 — JS/TS + Go adapters (`LanguageAdapter` plugin layer + ordered registry; Pytest/Node/
      Go adapters; generic `run_tests`; allowlist += node/npm/npx/go/pip; per-language sandbox images;
      red→fix→green verified in all three languages)
- [x] Phase 9 — security hardening + red-team suite ⭐ (C4 redaction filter; `tests/redteam/`
      proving C1–C5 across §5 categories 1–7; 62 red-team tests green, live container checks pass)
- [x] Phase 10 — observability + cost (cost accounting + USD price table; replayable secret-free
      TRACE artifact + Langfuse mirror; resolve/regression/time-to-fix/cost-per-fix metrics + `/metrics`)
- [x] Phase 11 — eval harness (custom buggy-commit set offline-tested + SWE-bench-lite loader gated;
      resolve/regression scoring reusing `app.telemetry.metrics`; `score_delta` tuning loop;
      `bugfix-eval run` prints the headline number — real-API baseline 100% (3/3), $0.208)
- [x] Phase 12 — React dashboard (Vite+React+Tailwind; list/detail/diff/reasoning; live SSE log;
      approve/reject wired to the C1 gate + DB approval store + CORS; offline-tested backend + Vitest)
- [x] Phase 13 — proactive bug discovery (`app/discovery/` detectors → triage → promote; `scan`/
      `finding` tables; `bugfix-scan` CLI; `/findings` + `/scans` API + dashboard Findings tab;
      offline acceptance reproduce→verify→awaiting_approval + re-scan dedup)
- [x] Phase 14 — one-command local dev (`bugfix-bootstrap` wipe-then-scrape, `APP_ENV=local` guard,
      `list_open_issues`; `npm run dev` orchestration via concurrently + wait-on; `SCRAPE_*` settings)
- [x] Phase 8+ — extended language adapters (Rust, Ruby, Java/Kotlin Maven+Gradle, .NET, PHP, Elixir;
      shared `BaseRegexAdapter`; sandbox images; allowlist + registry wired)
- [ ] Phase 15 — deploy + CI/CD (Fly.io, migrations, rollback)  *(was Phase 13)*
- [ ] Phase 16 — docs + demo + final eval number  *(was Phase 14)*

## Blockers / needed before building

1. **Docker** access (Phases 2, 3, 7, 9, 13, 14, 15 depend on it). Sandbox here has none.
2. **Anthropic API key** for the agent loop (Phases 3, 4) — provided at runtime, never committed.
3. **GitHub App** created + installed on a test repo (Phase 5) — app id, private key, webhook
   secret, installation id. Required before any real PR.
4. Confirm the open decisions in `ARCHITECTURE.md` §11 (Python 3.12 target, Fly sandbox host
   model, Langfuse self-host vs cloud, embedding provider).

## Decisions on record

- Session = plan/architecture only; code deferred until access is provided.
- Tech stack is locked per the build spec (FastAPI/Postgres/Redis-arq/pgvector/tree-sitter/
  Docker/GitHub App/Langfuse/React-Vite-Tailwind/Fly.io).
- Never-cut phases: 4 (core loop), 5 (PR gate), 9 (security). Cut-order documented in BUILD_PLAN.

## Next session: suggested first move

Start Phase 0 scaffold (no external access needed) so Phase 1 can begin the moment Docker/keys
land. Phase 1's repo-brain CLI is also buildable + testable without Docker or an API key.

---
_Last updated: 2026-06-30 — Phases 13 + 14 complete and the language-adapter set extended. Phase 13:
proactive discovery (`app/discovery/` detectors → triage → promote; `scan`/`finding` tables + migration;
`bugfix-scan`; `/findings` + `/scans` + dashboard Findings tab; reproduction is the precision filter).
Phase 14: one-command `npm run dev` (`bugfix-bootstrap` wipe-then-scrape, `APP_ENV=local` guard,
`list_open_issues`). Adapters: Rust/Ruby/JVM(Maven+Gradle)/.NET/PHP/Elixir on a shared `BaseRegexAdapter`.
Whole offline Python suite: **336 passed, 1 skipped**; ruff + format + mypy clean; alembic drift-free.
Frontend: **14 vitest tests** + `tsc` green._
