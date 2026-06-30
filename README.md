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
- ⬜ Phases 5–14: see the build plan.

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

## Layout

```
app/
  api/        HTTP surface (Phase 6+)
  agent/      tool-use loop + allowlist (Phase 3+)
  vcs/        GitHub App + draft PR — sole remote-write owner (Phase 5+)
  sandbox/    ephemeral container isolation (Phase 2+)
  index/      repo brain: clone, symbols, search, retrieval  ← Phase 1
  runner/     test detection + stack-trace parsing (Phase 2+)
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
