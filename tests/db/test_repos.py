import pytest

from app.db.repos import create_repo, delete_repo, list_repos, parse_repo_url
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
        ("https://github.com/octo/demo", "octo/demo"),
        ("https://github.com/octo/demo.git", "octo/demo"),
        ("git@github.com:octo/demo.git", "octo/demo"),
        ("octo/demo", "octo/demo"),
    ],
)
def test_parse_repo_url_ok(url, expected):
    assert parse_repo_url(url) == expected


@pytest.mark.parametrize("bad", ["", "https://gitlab.com/a/b", "not a url", "octo"])
def test_parse_repo_url_bad(bad):
    with pytest.raises(ValueError):
        parse_repo_url(bad)


@pytest.mark.asyncio
async def test_create_list_delete(db_session):
    repo = await create_repo(db_session, "octo/demo")
    assert repo.installation_id is None
    assert [r.full_name for r in await list_repos(db_session)] == ["octo/demo"]
    with pytest.raises(ValueError):
        await create_repo(db_session, "octo/demo")  # duplicate
    await delete_repo(db_session, repo.id)
    assert await list_repos(db_session) == []
