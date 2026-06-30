"""Minimal GitHub REST client for the remote-write path (Phase 5).

Only the calls the human-gated draft-PR flow needs: read an issue, create a
branch, commit files via the Git Data API, open a **draft** PR, and post a
comment. There is deliberately **no merge, no push-to-default, and no
non-draft-PR code path** (SECURITY.md C1) — the capability simply does not exist
in this client.

The installation token is passed in and lives only on the client instance for
its lifetime; the ``Authorization`` header is never logged.
"""

from __future__ import annotations

import base64
from types import TracebackType
from typing import Any

import httpx

from app.vcs.auth import GITHUB_API, InstallationToken
from app.vcs.models import DraftPR, FileChange, RepoRef

_BLOB_MODE = "100644"  # normal non-executable file


class GitHubError(Exception):
    """Raised when a GitHub API call returns an unexpected status."""


class GitHubClient:
    """Thin REST wrapper bound to one repo and one installation token."""

    def __init__(
        self,
        repo: RepoRef,
        token: InstallationToken,
        *,
        http: httpx.Client | None = None,
    ) -> None:
        self.repo = repo
        self._owns_http = http is None
        self._http = http or httpx.Client(timeout=30.0)
        self._headers = {
            "Authorization": f"token {token.value}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # -- lifecycle -------------------------------------------------------
    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- low-level -------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{GITHUB_API}/repos/{self.repo.full_name}{path}"

    def _request(self, method: str, path: str, *, json: Any = None, ok: int = 200) -> Any:
        resp = self._http.request(method, self._url(path), headers=self._headers, json=json)
        if resp.status_code != ok:
            # Redact: include status + endpoint, never the auth header or token.
            raise GitHubError(f"{method} {path} -> HTTP {resp.status_code}")
        return resp.json()

    # -- reads -----------------------------------------------------------
    def get_issue(self, number: int) -> dict[str, Any]:
        """Fetch issue title/body/labels for seeding a task."""
        data: dict[str, Any] = self._request("GET", f"/issues/{number}")
        return data

    def base_sha(self, branch: str) -> str:
        """Resolve a branch name to its current commit sha."""
        ref = self._request("GET", f"/git/ref/heads/{branch}")
        return str(ref["object"]["sha"])

    # -- writes (the only mutating calls; all gated upstream) ------------
    def _create_blob(self, content: str) -> str:
        data = self._request(
            "POST",
            "/git/blobs",
            json={"content": base64.b64encode(content.encode()).decode(), "encoding": "base64"},
            ok=201,
        )
        return str(data["sha"])

    def commit_files(
        self,
        *,
        base_branch: str,
        head_branch: str,
        message: str,
        changes: list[FileChange],
    ) -> str:
        """Create ``head_branch`` off ``base_branch`` with ``changes`` in one commit.

        Uses the Git Data API (blob → tree → commit → ref) so multiple files land
        in a single atomic commit. Returns the new commit sha. Never fast-forwards
        or touches the base branch.
        """
        if not changes:
            raise GitHubError("refusing to commit an empty change set")

        parent_sha = self.base_sha(base_branch)
        base_commit = self._request("GET", f"/git/commits/{parent_sha}")
        base_tree = base_commit["tree"]["sha"]

        tree_entries = [
            {
                "path": c.path,
                "mode": _BLOB_MODE,
                "type": "blob",
                "sha": self._create_blob(c.content),
            }
            for c in changes
        ]
        tree = self._request(
            "POST", "/git/trees", json={"base_tree": base_tree, "tree": tree_entries}, ok=201
        )
        commit = self._request(
            "POST",
            "/git/commits",
            json={"message": message, "tree": tree["sha"], "parents": [parent_sha]},
            ok=201,
        )
        commit_sha = str(commit["sha"])
        self._request(
            "POST",
            "/git/refs",
            json={"ref": f"refs/heads/{head_branch}", "sha": commit_sha},
            ok=201,
        )
        return commit_sha

    def open_draft_pr(self, *, title: str, head: str, base: str, body: str) -> DraftPR:
        """Open a pull request with ``draft=true`` — the only PR-creation path."""
        data = self._request(
            "POST",
            "/pulls",
            json={"title": title, "head": head, "base": base, "body": body, "draft": True},
            ok=201,
        )
        return DraftPR(number=int(data["number"]), url=str(data["html_url"]), head_branch=head)

    def comment(self, *, number: int, body: str) -> None:
        """Post a comment on the PR/issue (reasoning writeup goes here)."""
        self._request("POST", f"/issues/{number}/comments", json={"body": body}, ok=201)
