"""``image_available`` gates docker-marked tests on the image, not just the daemon.

Regression: CI has the ``docker`` CLI (so ``docker_available()`` was true) but the
``bugfix-sandbox`` image isn't built there, so the live red-team containers ran and
failed with exit 125 ("Unable to find image") instead of skipping.
"""

from __future__ import annotations

import pytest

from app.sandbox import image_available


def test_missing_docker_binary_means_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.sandbox.docker.shutil.which", lambda _: None)
    assert image_available("anything:latest") is False


def test_absent_image_is_unavailable() -> None:
    # No daemon or no such image -> `docker image inspect` is non-zero -> False.
    assert image_available("bugfix-nonexistent-image:does-not-exist") is False
