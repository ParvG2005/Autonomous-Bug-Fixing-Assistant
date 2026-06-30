# JS/TS execution sandbox (Phase 8 — per-language base image).
# Untrusted repo code runs here: no secrets, no egress (enforced at run time),
# non-root, capped resources. Toolchain baseline: Node (built-in `node --test`).
#
# Node ≥20 ships a TAP-emitting test runner with auto test-file discovery, so the
# common JS case needs no dependency install. Projects with their own jest/vitest
# deps install via npm when the runner is invoked with deps-install enabled.
#
# Build: docker build -t bugfix-sandbox-node:latest -f docker/sandbox.node.Dockerfile .
FROM node:22-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep \
    && rm -rf /var/lib/apt/lists/*

# node:22-slim already provides a non-root `node` user (uid 1000).
USER node
WORKDIR /workspace

CMD ["node", "--version"]
