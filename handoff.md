# Handoff — Autonomous Bug-Fixing Assistant

> Running progress log. Update this at the end of every working session: what got done, what's
> left, and anything the next session needs to know. Most recent entry on top.

## Current status: PHASES 0–8 COMPLETE — multi-language (Python, JS/TS, Go)

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
- [x] `docs/BUILD_PLAN.md` — phases 0–14 with goals/deliverables/acceptance/deps/size/risk,
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
- [ ] Phase 8 — JS/TS + Go adapters
- [ ] Phase 9 — security hardening + red-team suite ⭐
- [ ] Phase 10 — observability + cost (structlog, Langfuse, metrics)
- [ ] Phase 11 — eval harness (SWE-bench-lite + custom set)
- [ ] Phase 12 — React dashboard (SSE, approve/reject)
- [ ] Phase 13 — deploy + CI/CD (Fly.io, migrations, rollback)
- [ ] Phase 14 — docs + demo + final eval number

## Blockers / needed before building

1. **Docker** access (Phases 2, 3, 7, 9, 13 depend on it). Sandbox here has none.
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
_Last updated: 2026-06-30 — Phase 7 complete (async workers: queue, state machine, pipeline → human
gate, crash recovery, /jobs status + SSE logs)._
