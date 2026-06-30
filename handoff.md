# Handoff — Autonomous Bug-Fixing Assistant

> Running progress log. Update this at the end of every working session: what got done, what's
> left, and anything the next session needs to know. Most recent entry on top.

## Current status: PHASES 0 + 1 + 2 COMPLETE — runner executes tests in a sandbox

Phases 0–2 are built, tested, and lint/type-clean. The test runner detects pytest, executes it
inside a capped ephemeral Docker container, and parses results into structured failures with
`{file, line, function}` frames. Next: Phase 3 (agent loop — Anthropic key is set).

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
- [ ] Phase 3 — agent loop (needs Anthropic key)
- [ ] Phase 4 — issue→reproduce→localize→fix→explain ⭐ core milestone
- [ ] Phase 5 — GitHub integration, human-gated draft PR ⭐
- [ ] Phase 6 — FastAPI + Postgres/Alembic + webhook
- [ ] Phase 7 — arq workers + state machine
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
_Last updated: 2026-06-30 — design baseline._
