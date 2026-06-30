"""Worker tasks for the UI control plane: GitHub I/O kept off the API process.

``connect_repo`` / ``scan_repo`` / ``publish_pr`` are enqueued by the API and run
here where network + token minting are allowed (SECURITY.md C4).
"""

from __future__ import annotations

from typing import Any

from app.telemetry.logging import get_logger

log = get_logger("workers.control")


async def connect_repo(ctx: dict[str, Any], repo_id: str) -> str:
    raise NotImplementedError  # Task 4


async def scan_repo(ctx: dict[str, Any], repo_id: str) -> str:
    raise NotImplementedError  # Task 5


async def publish_pr(ctx: dict[str, Any], job_id: str) -> str:
    raise NotImplementedError  # Task 8
