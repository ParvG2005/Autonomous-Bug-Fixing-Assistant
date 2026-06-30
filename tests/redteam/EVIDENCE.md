# Red-Team Evidence — Phase 9

Maps SECURITY.md §5 categories and §3 constraints (C1–C5) to the tests that prove
them. Run the whole suite with `pytest -m redteam`; live container checks also carry
`@pytest.mark.docker` and skip without a Docker daemon.

| SECURITY.md category | Constraint | Test(s) |
|---|---|---|
| 1. Prompt injection (issue/comment/code/filename) | C3 | `test_c3_prompt_injection.py` — corpus replay, compliant-agent push attempt contained, execution plane can't import `app.vcs` |
| 2. Egress (DNS/HTTP/socket) | C2 | `test_c2_sandbox.py::test_docker_run_is_locked_down`, `::test_live_egress_is_blocked` (docker) |
| 3. Filesystem escape / rootfs write | C2, C5 | `test_c2_sandbox.py::test_live_rootfs_is_read_only` (docker); `test_c5_allowlist.py::test_path_traversal_rejected_on_read_and_edit` |
| 4. Resource exhaustion (CPU/mem/PID/time) | C2 | `test_c2_sandbox.py::test_docker_run_is_locked_down`, `::test_live_pid_cap_contains_fork_bomb` (docker) |
| 5. Secret exfiltration (env dump, token print, log poisoning) | C4 | `test_c4_secret_isolation.py` — token repr redaction, `scrub`/processor, end-to-end log scrub, model-context has no secret |
| 6. Remote-write coercion (push/force/non-draft/merge) | C1 | `test_c1_human_gate.py` — no-approval refused before mint, rejected refused, `draft=true` enforced, no merge/ready-PR capability |
| 7. Allowlist bypass / traversal / arg fuzz | C5 | `test_c5_allowlist.py` — unknown tool, disallowed commands, traversal, argument fuzz |

## Controls added/closed in Phase 9

- **C4 redaction filter** (`app/telemetry/redaction.py`): a structlog processor that
  scrubs GitHub token families, fine-grained PATs, JWTs, and inline auth headers from
  every event, plus value-level redaction for sensitive-named keys. Wired into
  `configure_logging` ahead of the renderer. The rest of C1–C5 were already enforced in
  code by Phases 2–8; this suite is the adversarial proof that they hold.

## Residual (tracked in SECURITY.md §6)

- Live C2 strength depends on the Fly host model (DinD vs. dedicated worker VM).
- `run_command` allowlists `argv[0]` only; `pip install <evil>` is contained by
  egress-off + the sandbox, not by the allowlist itself.
