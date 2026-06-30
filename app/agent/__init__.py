"""Tool-use loop, planner, prompt templates, retry/budget controller, tool
dispatch + allowlist enforcement (Phase 3+).

Mediates untrusted input. Tool calls are validated against
``app.core.allowlist`` before dispatch.
"""
