import pytest

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
