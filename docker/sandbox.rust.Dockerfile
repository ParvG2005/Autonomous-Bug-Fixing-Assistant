# Rust execution sandbox (Phase 8 — per-language base image).
# Untrusted repo code runs here: no secrets, no egress (enforced at run time),
# non-root, capped resources. Toolchain baseline: the Rust toolchain (`cargo test`).
#
# Build: docker build -t bugfix-sandbox-rust:latest -f docker/sandbox.rust.Dockerfile .
FROM rust:1.81-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Cargo home on a writable path the non-root user owns (workspace is the only mount).
ENV CARGO_HOME=/tmp/cargo CARGO_TARGET_DIR=/tmp/target

RUN useradd --create-home --uid 10001 sandbox
USER sandbox
WORKDIR /workspace

CMD ["cargo", "--version"]
