"""GitHub client: atomic Git-Data commit, draft-only PR, no merge path."""

from __future__ import annotations

import json

import httpx

from app.vcs.auth import InstallationToken
from app.vcs.github import GitHubClient
from app.vcs.models import FileChange, RepoRef

_REPO = RepoRef(owner="acme", name="widget", installation_id=1)
_TOKEN = InstallationToken(value="ghs_x", expires_at="")


def _client(handler: httpx.MockTransport) -> GitHubClient:
    return GitHubClient(_REPO, _TOKEN, http=httpx.Client(transport=handler))


def test_commit_files_walks_git_data_api() -> None:
    seen: list[tuple[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        seen.append((req.method, path))
        if path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "base-sha"}})
        if path.endswith("/git/commits/base-sha"):
            return httpx.Response(200, json={"tree": {"sha": "base-tree"}})
        if path.endswith("/git/blobs"):
            return httpx.Response(201, json={"sha": "blob-sha"})
        if path.endswith("/git/trees"):
            body = json.loads(req.content)
            assert body["base_tree"] == "base-tree"
            return httpx.Response(201, json={"sha": "new-tree"})
        if path.endswith("/git/commits"):
            return httpx.Response(201, json={"sha": "new-commit"})
        if path.endswith("/git/refs"):
            body = json.loads(req.content)
            assert body["ref"] == "refs/heads/fix/job-1"
            return httpx.Response(201, json={})
        raise AssertionError(f"unexpected {path}")

    client = _client(httpx.MockTransport(handler))
    sha = client.commit_files(
        base_branch="main",
        head_branch="fix/job-1",
        message="fix it",
        changes=[FileChange(path="calc.py", content="x = 1\n")],
    )
    assert sha == "new-commit"
    assert ("POST", "/repos/acme/widget/git/refs") in seen


def test_open_draft_pr_always_sets_draft_true() -> None:
    captured: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured.update(json.loads(req.content))
        return httpx.Response(
            201, json={"number": 7, "html_url": "https://github.com/acme/widget/pull/7"}
        )

    pr = _client(httpx.MockTransport(handler)).open_draft_pr(
        title="Fix", head="fix/job-1", base="main", body="why"
    )
    assert captured["draft"] is True
    assert pr.number == 7
    assert pr.url.endswith("/pull/7")


def test_no_merge_capability_exists() -> None:
    """C1: the client must expose no way to merge or push to the base branch."""
    names = dir(GitHubClient)
    assert not any("merge" in n.lower() for n in names)
    assert "comment" in names and "open_draft_pr" in names
