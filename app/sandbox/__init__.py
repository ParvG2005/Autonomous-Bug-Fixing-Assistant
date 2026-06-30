"""Container lifecycle, resource caps, egress control, capability dropping,
workspace mounts (Phase 2+).

The isolation boundary. One ephemeral container per job; no secrets, no egress.
A local subprocess fallback exists for dev machines and is disabled when
``Settings.is_deployed``.
"""
