# Base image for the per-job execution sandbox (Phase 2).
# Untrusted repo code runs here: no secrets, no egress (enforced at run time),
# non-root, capped resources. This is the toolchain baseline + pytest.
#
# Build: docker build -t bugfix-sandbox:latest -f docker/sandbox.Dockerfile .
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep \
    && rm -rf /var/lib/apt/lists/*

# pytest is the Phase 2 runner; pinned-ish to a recent major.
RUN pip install --no-cache-dir "pytest>=8.2"

# Non-root by default; the worker mounts a writable workspace volume.
RUN useradd --create-home --uid 10001 sandbox
USER sandbox
WORKDIR /workspace

CMD ["python", "--version"]
