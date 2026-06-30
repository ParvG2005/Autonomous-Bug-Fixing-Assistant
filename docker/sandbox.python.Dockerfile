# Python execution sandbox (Phase 8 — per-language base image).
# Untrusted repo code runs here: no secrets, no egress (enforced at run time),
# non-root, capped resources. Toolchain baseline: python + pytest.
#
# Build: docker build -t bugfix-sandbox-python:latest -f docker/sandbox.python.Dockerfile .
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "pytest>=8.2"

RUN useradd --create-home --uid 10001 sandbox
USER sandbox
WORKDIR /workspace

CMD ["python", "--version"]
