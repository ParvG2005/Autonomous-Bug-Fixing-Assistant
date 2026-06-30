# Data Model — Autonomous Bug-Fixing Assistant

> Postgres + SQLAlchemy 2.0 (async) + Alembic. pgvector for embeddings. This is the logical
> model; column types are indicative, not final DDL. Secrets are never stored here in plaintext.

## 1. Entity overview

```mermaid
erDiagram
    REPO ||--o{ JOB : "has"
    JOB ||--o{ RUN : "has"
    JOB ||--o| FIX : "produces"
    JOB ||--o| APPROVAL : "gated by"
    RUN ||--o{ ARTIFACT : "emits"
    FIX ||--o{ ARTIFACT : "references"
    REPO ||--o{ CODE_CHUNK : "indexed as"
    REPO ||--o{ SCAN : "hunted by"
    SCAN ||--o{ FINDING : "yields"
    FINDING ||--o| JOB : "promoted to"

    REPO {
        uuid id PK
        bigint gh_repo_id "GitHub numeric id"
        string full_name "owner/name"
        bigint installation_id "GitHub App install"
        string default_branch
        string language "detected primary"
        timestamptz created_at
    }
    JOB {
        uuid id PK
        uuid repo_id FK
        bigint gh_issue_number
        uuid finding_id "nullable; set when promoted from discovery"
        string trigger "webhook|manual|eval|discovery|scrape"
        text issue_title
        text issue_body_ref "artifact id, not inline"
        string state "see state machine"
        string failure_reason "nullable"
        jsonb budget "token/time/retry ceilings"
        jsonb cost "tokens, usd, wall_ms"
        timestamptz created_at
        timestamptz updated_at
    }
    RUN {
        uuid id PK
        uuid job_id FK
        int attempt "1..N within budget"
        string phase "reproduce|localize|fix|verify"
        string status "ok|fail|error"
        string langfuse_trace_id
        jsonb metrics
        timestamptz started_at
        timestamptz ended_at
    }
    ARTIFACT {
        uuid id PK
        uuid run_id FK "nullable"
        uuid job_id FK
        string kind "diff|test_output|stacktrace|log|reasoning|issue_body"
        string storage "inline_small|blob_ref"
        text content "nullable if blob"
        string blob_url "nullable"
        bigint size_bytes
        string sha256
        timestamptz created_at
    }
    FIX {
        uuid id PK
        uuid job_id FK
        uuid diff_artifact_id FK
        uuid reasoning_artifact_id FK
        int diff_lines_added
        int diff_lines_removed
        bool wrote_repro_test
        jsonb flags "touched_ci|touched_lockfile|secret_like|oversize"
        bool tests_pass "post-fix verification"
        timestamptz created_at
    }
    APPROVAL {
        uuid id PK
        uuid job_id FK
        string decision "approved|rejected"
        string actor "human identity"
        string actor_source "dashboard|api"
        text note
        timestamptz decided_at
    }
    CODE_CHUNK {
        uuid id PK
        uuid repo_id FK
        string path
        int start_line
        int end_line
        string symbol "nullable"
        vector embedding "pgvector"
        timestamptz indexed_at
    }
    SCAN {
        uuid id PK
        uuid repo_id FK
        string trigger "scheduled|manual|push"
        string state "running|done|failed"
        jsonb sources_run
        jsonb budget "max_jobs"
        timestamptz created_at
    }
    FINDING {
        uuid id PK
        uuid scan_id FK
        uuid repo_id FK
        string source "tests|static|runtime|diff|review"
        string fingerprint "dedup key, unique per repo"
        text summary
        text evidence "untrusted-as-artifact"
        jsonb frames
        float confidence
        string severity
        string status "candidate|reproduced|promoted|dismissed|duplicate"
        uuid job_id FK "nullable; set on promotion"
        timestamptz created_at
    }
```

## 2. Table notes

- **REPO** — one row per installed repo. `installation_id` links to the GitHub App install used
  to mint short-lived tokens at PR time; the token itself is never stored.
- **JOB** — the unit of work. `issue_body_ref` points at an ARTIFACT rather than inlining
  untrusted issue text into a hot table. `budget` captures the ceilings the agent runs under;
  `cost` is the running tally (filled by telemetry).
- **RUN** — one per attempt-phase. Holds the `langfuse_trace_id` so a row links straight to its
  full agent trace. Multiple runs per job because the agent self-corrects within budget.
- **ARTIFACT** — append-only. Small payloads inline; large ones (full diffs, logs) stored as a
  blob and referenced. `sha256` lets the dashboard and eval harness verify integrity.
- **FIX** — the proposed patch. `flags` carries the guardrail outcomes (oversize diff, touched
  CI/lockfile, secret-like content). A fix can exist with `tests_pass=false`; it just won't be
  eligible to advance past the gate.
- **APPROVAL** — **the human gate, persisted.** No remote write happens unless an `approved`
  row exists for the job. Immutable once written; a reversal is a new row.
- **CODE_CHUNK** — pgvector embeddings for fallback semantic retrieval; rebuilt per repo index.
- **SCAN** (Phase 13) — one proactive bug-hunt over a repo. `sources_run` records which detectors
  ran; `budget` caps how many findings may be promoted to jobs.
- **FINDING** (Phase 13) — a discovery candidate. `fingerprint` (rule id + normalized location +
  symbol) is **unique per repo**, so a re-scan can never refile a known finding. `evidence` holds
  untrusted scanner/stacktrace output, treated as an artifact (never executed at rest). On
  promotion, `status` becomes `promoted` and `job_id` links the discovery JOB (which carries
  `finding_id` back). Reproduction — not the finder — is the precision filter.

## 3. Job state machine

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> running : worker picks up
    running --> awaiting_approval : verified fix + draft artifacts ready
    running --> failed : budget exceeded / unrecoverable / no repro
    awaiting_approval --> approved : human approves (APPROVAL row)
    awaiting_approval --> rejected : human rejects (APPROVAL row)
    approved --> done : draft PR opened
    rejected --> done : no remote action, closed out
    failed --> [*]
    done --> [*]
```

Rules:
- The transition `approved → done` is the **only** path that triggers a remote write, and it is
  executed solely by `app/vcs` after reading the APPROVAL row.
- A job in `awaiting_approval` holds no live token and no running container — it is inert until a
  human acts.
- Crash recovery (Phase 7): a worker dying mid-`running` leaves the job re-claimable; idempotency
  keys on RUN attempts prevent double work. `awaiting_approval`/`failed`/`done` are terminal to
  workers.

## 4. Invariants (enforced in code + tested)

1. No row, column, log line, or artifact ever contains a GitHub token or API key in plaintext.
2. A draft PR (recorded as a `done` job with a PR url artifact) implies a matching `approved`
   APPROVAL row with an earlier `decided_at`.
3. `FIX.flags.oversize == true` or any `touched_*` flag blocks auto-advance; the gate still
   requires a human, and the dashboard surfaces the flag prominently.
4. ARTIFACT is append-only; FIX and APPROVAL are immutable after creation.

## 5. Indexes & retrieval

- B-tree: `job(repo_id, state)`, `run(job_id, attempt)`, `artifact(job_id, kind)`,
  `approval(job_id)`.
- pgvector: IVFFlat/HNSW index on `code_chunk.embedding`, scoped by `repo_id` at query time.
- Retrieval order at agent time: ripgrep + symbol index first; pgvector nearest-neighbor only as
  fallback (see ARCHITECTURE.md §8).

## 6. Migrations

Alembic from day one (Phase 6). Each phase that adds tables ships its own migration; no manual
schema edits. Migrations run on deploy (Phase 13) before the new image takes traffic.
