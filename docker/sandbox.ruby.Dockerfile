# Ruby execution sandbox (Phase 8 — per-language base image).
# Untrusted repo code runs here: no secrets, no egress, non-root, capped.
# Toolchain baseline: Ruby + RSpec/Bundler.
#
# Build: docker build -t bugfix-sandbox-ruby:latest -f docker/sandbox.ruby.Dockerfile .
FROM ruby:3.3-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && gem install rspec --no-document

ENV GEM_HOME=/tmp/gems BUNDLE_PATH=/tmp/bundle
ENV PATH="/tmp/gems/bin:${PATH}"

RUN useradd --create-home --uid 10001 sandbox
USER sandbox
WORKDIR /workspace

CMD ["ruby", "--version"]
