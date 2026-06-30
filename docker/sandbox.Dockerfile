# Base image for the per-job execution sandbox (Phase 2 fills this out).
# Untrusted repo code runs here: no secrets, no egress (enforced at run time),
# non-root, capped resources. This is just the toolchain baseline.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Non-root by default; the worker mounts a writable workspace volume.
RUN useradd --create-home --uid 10001 sandbox
USER sandbox
WORKDIR /workspace

CMD ["python", "--version"]
