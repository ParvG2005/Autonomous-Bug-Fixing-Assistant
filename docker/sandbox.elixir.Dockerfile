# Elixir execution sandbox (Phase 8 — per-language base image).
# Untrusted repo code runs here: no secrets, no egress, non-root, capped.
# Toolchain baseline: Elixir + Mix (`mix test`).
#
# Build: docker build -t bugfix-sandbox-elixir:latest -f docker/sandbox.elixir.Dockerfile .
FROM elixir:1.17-otp-27

RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Hex/Mix caches on writable, user-owned paths (workspace is the only mount).
ENV MIX_HOME=/tmp/mix HEX_HOME=/tmp/hex HOME=/tmp

RUN useradd --create-home --uid 10001 sandbox
USER sandbox
WORKDIR /workspace

CMD ["elixir", "--version"]
