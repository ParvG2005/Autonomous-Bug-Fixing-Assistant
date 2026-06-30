# Docs — Autonomous Bug-Fixing Assistant

Design baseline for a system that takes a GitHub issue on a Python repo and autonomously
reproduces, localizes, fixes, verifies, and explains the bug — then opens a **draft** PR gated on
human approval. No code yet; these documents are the contract the build executes against.

## Read in this order

1. **[ARCHITECTURE.md](./ARCHITECTURE.md)** — what the system is, its components, and the
   control-plane / execution-plane split that keeps untrusted code away from credentials.
2. **[DATA_MODEL.md](./DATA_MODEL.md)** — entities, ERD, the job state machine, and the
   human-gate invariant.
3. **[SEQUENCE_DIAGRAMS.md](./SEQUENCE_DIAGRAMS.md)** — the four key flows end to end.
4. **[SECURITY.md](./SECURITY.md)** — threat model, the five non-negotiable constraints mapped
   to controls and tests, and the red-team plan.
5. **[BUILD_PLAN.md](./BUILD_PLAN.md)** — phases 0–14 with acceptance tests, dependency graph,
   critical path, cut-order, and stop-and-ask gates.

Progress tracking lives in **[../handoff.md](../handoff.md)** (updated each session).

## Non-negotiables (never violated)

1. Human gate — only **draft** PRs, only after a recorded approval; no merge path exists.
2. Sandboxed execution — one ephemeral container per job, non-root, caps dropped, egress off.
3. Untrusted input — issue/code/comment/filename text can never reach secrets or remote-write.
4. Secret isolation — tokens short-lived, per-install, never in model context or logs.
5. Allowlist — every agent tool call is validated before execution.

## Never-cut phases

Phase 4 (core loop), Phase 5 (PR gate), Phase 9 (security). Everything else has a documented
cut-order in `BUILD_PLAN.md`.
