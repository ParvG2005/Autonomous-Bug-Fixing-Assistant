# Sequence Diagrams — Autonomous Bug-Fixing Assistant

> The four flows that matter. Each maps to phases in `BUILD_PLAN.md`. Mermaid renders on GitHub
> and most markdown viewers.

## 1. Issue labeled → queued job (Phase 6)

```mermaid
sequenceDiagram
    autonumber
    participant Dev as Developer
    participant GH as GitHub
    participant API as FastAPI /webhooks
    participant DB as Postgres
    participant Q as Redis/arq

    Dev->>GH: add label "autofix" to issue
    GH->>API: webhook (issues.labeled), HMAC-signed
    API->>API: verify webhook signature (reject if bad)
    API->>API: validate payload, treat issue text as untrusted
    API->>DB: upsert REPO, store issue body as ARTIFACT
    API->>DB: insert JOB (state=queued)
    API->>Q: enqueue job(id)
    API-->>GH: 202 Accepted
    Note over API,GH: No work done synchronously — webhook returns fast.
```

## 2. Worker orchestration: full pipeline (Phases 3–4, 7)

```mermaid
sequenceDiagram
    autonumber
    participant Q as Redis/arq
    participant W as Worker
    participant DB as Postgres
    participant SB as Ephemeral container
    participant AG as Agent loop
    participant LF as Langfuse

    Q->>W: deliver job(id)
    W->>DB: JOB state running
    W->>SB: create container (non-root, no egress, caps dropped)
    W->>SB: stream clone repo into workspace (control plane has no creds in container)
    W->>SB: build tree-sitter index + ripgrep ready
    W->>AG: start (issue task, budget)
    AG->>LF: open trace

    rect rgb(235,240,255)
    Note over AG,SB: Reproduce
    AG->>SB: run_tests / run_command (allowlisted)
    SB-->>AG: pass/fail + parsed stacktrace frames
    AG->>SB: if no failing test, edit_file to WRITE a repro test
    end

    rect rgb(235,255,240)
    Note over AG,SB: Localize
    AG->>SB: search (ripgrep), find_symbol, read_file
    SB-->>AG: candidate files ranked
    end

    rect rgb(255,245,235)
    Note over AG,SB: Fix + verify (loop within budget)
    AG->>SB: edit_file (guardrails: size, CI/lockfile/secret flags)
    AG->>SB: run_tests
    SB-->>AG: green? -> stop. red? -> self-correct (retry budget)
    end

    AG->>LF: close trace (tool calls, tokens)
    AG-->>W: diff + reasoning + repro flag + flags
    W->>DB: insert FIX + ARTIFACTs (diff, reasoning)
    W->>DB: JOB state awaiting_approval
    W->>SB: destroy container
    Note over W,DB: No token minted, no remote touched. Job is inert until a human acts.
```

## 3. Human gate → draft PR (Phase 5)

```mermaid
sequenceDiagram
    autonumber
    participant Human as Reviewer
    participant UI as Dashboard
    participant API as FastAPI
    participant DB as Postgres
    participant VCS as app/vcs (privileged)
    participant SM as core: secret broker
    participant GH as GitHub

    Human->>UI: review diff + reasoning trace
    alt approve
        Human->>UI: click Approve
        UI->>API: POST /jobs/{id}/approve
        API->>DB: insert APPROVAL(decision=approved, actor=human)
        API->>VCS: request open_draft_pr(job)
        VCS->>DB: assert APPROVAL row exists (else abort)
        VCS->>SM: mint short-lived installation token (scoped to repo)
        SM-->>VCS: token (in memory only, never logged/stored)
        VCS->>GH: create branch + commit fix
        VCS->>GH: open DRAFT PR + post reasoning as comment
        GH-->>VCS: PR url
        VCS->>DB: JOB state done, store PR url ARTIFACT
        VCS->>VCS: discard token
    else reject
        Human->>UI: click Reject
        UI->>API: POST /jobs/{id}/reject
        API->>DB: insert APPROVAL(decision=rejected), JOB state done
        Note over API,GH: No remote action whatsoever.
    end
```

Hard rule shown above: `VCS` refuses to act unless it can read an `approved` APPROVAL row, and
the token is minted *inside* that path, used, and discarded. The agent never sees it.

## 4. Live status to the dashboard (Phase 12)

```mermaid
sequenceDiagram
    autonumber
    participant UI as Dashboard
    participant API as FastAPI /runs/{id}/events (SSE)
    participant DB as Postgres
    participant W as Worker

    UI->>API: open SSE stream for job
    W->>DB: append run/phase updates + log lines
    loop while job not terminal
        API->>DB: poll/listen (LISTEN/NOTIFY)
        API-->>UI: SSE event (phase, status, log tail, cost)
    end
    API-->>UI: SSE event (awaiting_approval) -> show Approve/Reject
```

## Cross-references

- Trust-plane split and why the agent can't push: `ARCHITECTURE.md` §5.
- State transitions and the approval invariant: `DATA_MODEL.md` §3–4.
- Isolation controls behind "no egress / caps dropped": `SECURITY.md`.
