"""Static-analysis signal (cheap, deterministic).

Run language-native analyzers **inside the sandbox** and turn their structured
output into candidates. We lead with the cheap deterministic signal (mirroring
the repo's ripgrep-before-vectors philosophy): ``mypy`` for type errors / None
derefs and ``ruff`` for lint-class bugs. Each finding carries a file/line/rule, so
its fingerprint is stable and its location seeds localization for free.

Tools that are not installed degrade to *no* candidates (never an error): a
missing analyzer simply contributes no signal.
"""

from __future__ import annotations

import json
import re

from app.discovery.finding import Candidate
from app.discovery.sources.base import ScanContext
from app.models.entities import FindingSource
from app.sandbox.models import ExecResult, ResourceLimits
from app.telemetry.logging import get_logger

log = get_logger("discovery.static")

# Lint codes that are far likelier to be real bugs than style nits — only these
# become candidates (recall is still cheap; precision comes from reproduction).
_RUFF_BUG_PREFIXES = ("F", "B", "E711", "E712", "E713", "E714", "E722", "PLE", "RUF")
# mypy text line: ``path:line: error: message  [code]``
_MYPY_RE = re.compile(
    r"^(?P<path>[^:]+):(?P<line>\d+):(?:\d+:)?\s*error:\s*(?P<msg>.+?)(?:\s+\[(?P<code>[\w-]+)\])?$"
)
# mypy codes that point at latent runtime crashes worth reproducing.
_MYPY_BUG_CODES = {
    "union-attr", "attr-defined", "index", "operator", "arg-type",
    "return-value", "call-arg", "assignment", "name-defined",
}


class StaticAnalysisDetector:
    """mypy + ruff, parsed into candidates. Missing tools contribute nothing."""

    source = FindingSource.STATIC

    def detect(self, ctx: ScanContext) -> list[Candidate]:
        limits = ctx.limits or ResourceLimits()
        out: list[Candidate] = []
        out += self._run_mypy(ctx, limits)
        out += self._run_ruff(ctx, limits)
        log.info("static_detector", emitted=len(out))
        return out[: ctx.max_candidates]

    def _safe_run(
        self, ctx: ScanContext, cmd: list[str], limits: ResourceLimits
    ) -> ExecResult | None:
        try:
            return ctx.sandbox.run(cmd, ctx.workspace, limits)
        except FileNotFoundError:
            log.info("static_tool_absent", tool=cmd[0])
            return None

    def _run_mypy(self, ctx: ScanContext, limits: ResourceLimits) -> list[Candidate]:
        res = self._safe_run(ctx, ["mypy", "--no-error-summary", "--no-color-output", "."], limits)
        if res is None:
            return []
        found: list[Candidate] = []
        for raw in (res.stdout + "\n" + res.stderr).splitlines():
            m = _MYPY_RE.match(raw.strip())
            if m is None:
                continue
            code = m.group("code") or ""
            if code and code not in _MYPY_BUG_CODES:
                continue
            found.append(
                Candidate(
                    source=FindingSource.STATIC,
                    summary=f"mypy: {m.group('msg')[:120]}",
                    rule=f"mypy:{code or 'error'}",
                    evidence=raw.strip(),
                    path=m.group("path"),
                    line=int(m.group("line")),
                    confidence=0.45,
                    severity="medium",
                )
            )
        return found

    def _run_ruff(self, ctx: ScanContext, limits: ResourceLimits) -> list[Candidate]:
        res = self._safe_run(ctx, ["ruff", "check", "--output-format=json", "."], limits)
        if res is None or not res.stdout.strip():
            return []
        try:
            items = json.loads(res.stdout)
        except json.JSONDecodeError:
            return []
        found: list[Candidate] = []
        for it in items if isinstance(items, list) else []:
            code = str(it.get("code") or "")
            if not code.startswith(_RUFF_BUG_PREFIXES):
                continue
            loc = it.get("location") or {}
            found.append(
                Candidate(
                    source=FindingSource.STATIC,
                    summary=f"ruff {code}: {str(it.get('message', ''))[:120]}",
                    rule=f"ruff:{code}",
                    evidence=f"{it.get('filename', '')}: {it.get('message', '')}",
                    path=str(it.get("filename") or ""),
                    line=int(loc.get("row") or 0) or None,
                    confidence=0.35,
                    severity="low",
                )
            )
        return found
