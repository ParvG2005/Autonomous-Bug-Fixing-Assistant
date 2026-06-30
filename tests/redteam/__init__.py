"""Red-team suite (Phase 9 / SECURITY.md §5).

Proves the five non-negotiable constraints C1-C5 against adversarial inputs.
Run with ``pytest -m redteam``. Offline by default; the live container-isolation
checks are additionally marked ``docker`` and skip without a Docker daemon.
"""
