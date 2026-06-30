# Smoke Test Runbook

Three levels, cheapest first. Level 0 needs nothing external. Level 1 proves the autonomous
core (needs an Anthropic key). Level 2 proves the full service path (needs Docker + a GitHub App).

Prereqs for all levels: `uv sync --dev`, then run tools via `uv run`. Copy `.env.example` → `.env`
and fill in as each level requires. Never commit `.env`.

---

## Level 0 — Offline wiring (no Docker, no API key, no network)

Proves the code installs, the suite is green, the schema builds, and the API/webhook path works.

```bash
uv sync --dev
uv run pytest -q -m "not docker and not integration"     # ~161 tests, all pass
uv run ruff check app && uv run mypy app                  # clean

# schema builds on a throwaway sqlite db
DATABASE_URL="sqlite+aiosqlite:////tmp/smoke.db" uv run alembic upgrade head

# CLIs load
uv run repo-brain --help && uv run bugfix-agent --help && uv run bugfix-pr --help
```

Expected: suite passes, `migrate OK`, every `--help` prints. This is the level reproducible on any
machine with no secrets. (Already verified in this repo.)

---

## Level 1 — Autonomous fix on a local buggy repo  ⭐ the one that matters

Proves the core loop: issue text → reproduce → localize → fix → verified green diff. No GitHub.

Needs `ANTHROPIC_API_KEY`. Docker optional — omit it and pass `--local` to use the subprocess
sandbox (fine for a smoke; weaker isolation).

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # runtime only, never committed

# make a tiny broken repo
mkdir -p /tmp/buggy && cd /tmp/buggy && git init -q
cat > calc.py <<'EOF'
def average(xs):
    return sum(xs) / (len(xs) - 1)   # off-by-one bug
EOF
cat > test_calc.py <<'EOF'
from calc import average
def test_average():
    assert average([2, 4, 6]) == 4
EOF
git add -A && git commit -qm init

# run the assistant against an issue description
cd /path/to/Autonomus-bug-fix-assistant
uv run bugfix-agent solve /tmp/buggy \
  --issue "average() returns the wrong value; ZeroDivisionError on single-element lists" \
  --writeup-out /tmp/writeup.md --local
```

Expected: console ends `RESOLVED`, a unified diff fixing the `- 1`, and `/tmp/writeup.md` with the
reasoning. With Docker instead of `--local`: first `docker build -t bugfix-sandbox:latest -f
docker/sandbox.Dockerfile .`, then drop `--local`.

The packaged version of this is the integration test:
```bash
ANTHROPIC_API_KEY=... uv run pytest -q -m integration tests/integration/test_solve_acceptance.py
```

---

## Level 2 — Full service path: webhook → worker → human gate → draft PR

Proves the deployed shape end to end. Needs Docker, Postgres, Redis, and a GitHub App.

### 2a. Bring up infra
```bash
docker compose up -d postgres redis          # from repo root
docker build -t bugfix-sandbox:latest -f docker/sandbox.Dockerfile .
# .env: set DATABASE_URL (postgres), REDIS_URL, ANTHROPIC_API_KEY,
#       GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY (PEM), GITHUB_WEBHOOK_SECRET
uv run alembic upgrade head
```

### 2b. Run API + worker
```bash
uv run bugfix-api          # terminal 1 — serves :8000
uv run bugfix-worker       # terminal 2 — drains the queue
```

### 2c. Fire a job — two options

**Option A (no GitHub yet): simulate the webhook locally.** Sign the payload with your
`GITHUB_WEBHOOK_SECRET` and POST it:
```bash
BODY='{"action":"labeled","label":{"name":"autofix"},
"issue":{"number":1,"title":"bug","body":"average() off-by-one in calc.py"},
"repository":{"id":1,"full_name":"you/disposable-repo","default_branch":"main"},
"installation":{"id":1}}'
SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$GITHUB_WEBHOOK_SECRET" | awk '{print $2}')"
curl -s localhost:8000/webhooks/github \
  -H "X-GitHub-Event: issues" -H "X-Hub-Signature-256: $SIG" \
  -H "Content-Type: application/json" -d "$BODY"
```

**Option B (real): install the GitHub App** on a disposable repo, point its webhook at your
`:8000/webhooks/github` (use a tunnel like cloudflared/ngrok for local), and add the `autofix`
label to a real issue.

### 2d. Watch it
```bash
curl -s localhost:8000/jobs | jq                 # find the job id
curl -N localhost:8000/jobs/<id>/logs            # live SSE log tail
curl -s localhost:8000/jobs/<id> | jq .state     # queued -> running -> awaiting_approval
```
Expected terminal state for a fixable bug: **`awaiting_approval`** (the pipeline parks here — it
never auto-publishes; that's the C1 human gate).

### 2e. Clear the human gate → draft PR  (STOP-AND-ASK)
Approval + publish is currently CLI-only (the API approve endpoint is the open gap):
```bash
uv run bugfix-pr status <id>
uv run bugfix-pr approve <id> --actor you
uv run bugfix-pr open <id> --confirm             # the ONLY remote write; opens a DRAFT PR
```
Expected: a **draft** PR on the disposable repo with the reasoning writeup posted as a comment.
Use a repo you own and can delete. Never run this against a repo you don't control.

---

## What each level tells you

| Level | Proves | Needs |
|---|---|---|
| 0 | installs, tests green, schema, API+webhook auth | nothing |
| 1 | the autonomous fix loop produces a verified patch | Anthropic key |
| 2 | webhook→worker→gate→draft PR, the deployed shape | Docker, PG, Redis, GitHub App |

Known gap: in Level 2, approval is a manual `bugfix-pr` hop because the approve/reject **API**
endpoint → publish wiring isn't built yet (lands with the Phase 12 dashboard).
