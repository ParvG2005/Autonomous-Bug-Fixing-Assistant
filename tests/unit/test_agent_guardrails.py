"""Tests for the Phase 4 edit guardrails: sensitive paths + diff-size cap."""

from __future__ import annotations

import pytest

from app.agent.guardrails import (
    DiffTooLarge,
    SensitivePath,
    check_diff_budget,
    sensitive_reason,
)


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        ".gitlab-ci.yml",
        "Jenkinsfile",
        ".circleci/config.yml",
    ],
)
def test_ci_config_is_sensitive(path: str) -> None:
    reason = sensitive_reason(path)
    assert reason is not None
    assert reason.kind == "ci-config"


@pytest.mark.parametrize(
    "path",
    ["uv.lock", "poetry.lock", "package-lock.json", "yarn.lock", "Cargo.lock", "go.sum"],
)
def test_lockfiles_are_sensitive(path: str) -> None:
    reason = sensitive_reason(path)
    assert reason is not None
    assert reason.kind == "lockfile"


@pytest.mark.parametrize(
    "path", [".env", ".env.production", "id_rsa", "server.pem", "secrets.yaml"]
)
def test_secrets_are_sensitive(path: str) -> None:
    reason = sensitive_reason(path)
    assert reason is not None
    assert reason.kind == "secret"


@pytest.mark.parametrize("path", ["calc.py", "src/app/main.py", "README.md", "test_calc.py"])
def test_ordinary_source_is_not_sensitive(path: str) -> None:
    assert sensitive_reason(path) is None


def test_sensitive_path_is_dataclass_with_reason() -> None:
    sp = sensitive_reason("uv.lock")
    assert isinstance(sp, SensitivePath)
    assert "lockfile" in str(sp).lower()


def test_diff_budget_passes_under_limit() -> None:
    diff = "--- a/x\n+++ b/x\n@@\n+one\n+two\n-old\n"
    check_diff_budget(diff, max_lines=10)  # no raise


def test_diff_budget_raises_over_limit() -> None:
    diff = "--- a/x\n+++ b/x\n@@\n" + "".join(f"+line{i}\n" for i in range(50))
    with pytest.raises(DiffTooLarge):
        check_diff_budget(diff, max_lines=10)


def test_diff_budget_ignores_header_lines() -> None:
    # The ---/+++ file headers must not count toward the changed-line budget.
    diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n+only one real change\n"
    check_diff_budget(diff, max_lines=1)  # no raise
