# Go execution sandbox (Phase 8 — per-language base image).
# Untrusted repo code runs here: no secrets, no egress (enforced at run time),
# non-root, capped resources. Toolchain baseline: the Go toolchain (`go test`).
#
# Go's testing framework is stdlib, so the common case needs no dependency
# install; `go mod download` runs only when deps-install is enabled.
#
# Build: docker build -t bugfix-sandbox-go:latest -f docker/sandbox.go.Dockerfile .
FROM golang:1.23-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep \
    && rm -rf /var/lib/apt/lists/*

# A writable module/build cache the non-root user owns (workspace is the only
# bind mount; GOCACHE/GOMODCACHE must live somewhere writable).
ENV GOCACHE=/tmp/go-build GOMODCACHE=/tmp/go-mod GOFLAGS=-mod=mod

RUN useradd --create-home --uid 10001 sandbox
USER sandbox
WORKDIR /workspace

CMD ["go", "version"]
