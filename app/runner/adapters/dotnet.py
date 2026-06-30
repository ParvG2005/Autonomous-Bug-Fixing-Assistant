"""·NET adapter — ``dotnet test`` (C#/F#/VB).

The .NET test platform drives xUnit/NUnit/MSTest uniformly. Stack frames read
``at Acme.CalcTest.Divide() in /src/CalcTest.cs:line 10``; the summary line is
``Failed: F, Passed: P, Skipped: S``.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.runner.adapters.common import BaseRegexAdapter, has_file_with_suffix
from app.runner.models import Framework

DOTNET_IMAGE = "bugfix-sandbox-dotnet:latest"

_FRAME_RE = re.compile(
    r"(?:at\s+(?P<func>[\w.<>`+]+)[^\n]*?\s+in\s+)?"
    r"(?P<file>[\w./@+-]+\.(?:cs|fs|vb)):line (?P<line>\d+)"
)
_SUMMARY_RE = re.compile(
    r"Failed:\s+(?P<failed>\d+),\s+Passed:\s+(?P<passed>\d+),\s+Skipped:\s+(?P<skipped>\d+)"
)


class DotnetTestAdapter(BaseRegexAdapter):
    framework = Framework.DOTNET
    image = DOTNET_IMAGE
    commands = frozenset({"dotnet"})
    frame_re = _FRAME_RE
    fail_marker = "Failed"

    def detect(self, workspace: Path) -> bool:
        return has_file_with_suffix(workspace, (".sln", ".csproj", ".fsproj", ".vbproj"))

    def install_command(self, workspace: Path) -> list[str] | None:
        return ["dotnet", "restore"]

    def build_command(self, targets: list[str] | None = None) -> list[str]:
        if targets:
            return ["dotnet", "test", "--filter", "|".join(targets)]
        return ["dotnet", "test"]

    def _count(self, combined: str) -> tuple[int, int, int]:
        m = _SUMMARY_RE.search(combined)
        if m is None:
            return (0, 0, 0)
        return (int(m.group("passed")), int(m.group("failed")), int(m.group("skipped")))
