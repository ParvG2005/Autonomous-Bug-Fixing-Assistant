import pytest

from app.db.repos import create_repo, delete_repo, list_repos, parse_repo_url, repo_clone_url
from app.models.entities import ArtifactKind, Repo


def test_bundle_artifact_kind_exists():
    assert ArtifactKind.BUNDLE.value == "bundle"


@pytest.mark.asyncio
async def test_repo_persists_without_install(db_session):
    repo = Repo(full_name="octo/demo", default_branch="main")
    db_session.add(repo)
    await db_session.flush()
    assert repo.id is not None
    assert repo.installation_id is None
    assert repo.gh_repo_id is None


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/octo/demo", ("octo/demo", None)),
        ("octo/demo", ("octo/demo", None)),
        ("git@github.com:octo/demo.git", ("octo/demo", None)),
        ("https://gitlab.com/grp/proj.git", ("grp/proj", "https://gitlab.com/grp/proj.git")),
        ("git@gitlab.com:grp/proj.git", ("grp/proj", "git@gitlab.com:grp/proj.git")),
        ("/Users/me/code/myrepo", ("myrepo", "/Users/me/code/myrepo")),
        ("file:///Users/me/code/myrepo", ("myrepo", "file:///Users/me/code/myrepo")),
    ],
)
def test_parse_repo_url_classifies_sources(url, expected):
    assert parse_repo_url(url) == expected


def test_parse_repo_url_rejects_empty():
    with pytest.raises(ValueError):
        parse_repo_url("")


def test_repo_clone_url_defaults_to_github_when_source_none():
    repo = Repo(full_name="octo/demo", default_branch="main", source_url=None)
    assert repo_clone_url(repo) == "https://github.com/octo/demo.git"


def test_repo_clone_url_uses_source_url_when_set():
    repo = Repo(full_name="octo/demo", default_branch="main", source_url="file:///tmp/demo")
    assert repo_clone_url(repo) == "file:///tmp/demo"


@pytest.mark.asyncio
async def test_create_list_delete(db_session):
    repo = await create_repo(db_session, "octo/demo")
    assert repo.installation_id is None
    assert [r.full_name for r in await list_repos(db_session)] == ["octo/demo"]
    with pytest.raises(ValueError):
        await create_repo(db_session, "octo/demo")  # duplicate
    await delete_repo(db_session, repo.id)
    assert await list_repos(db_session) == []
