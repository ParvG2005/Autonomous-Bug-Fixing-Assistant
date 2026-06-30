# PHP execution sandbox (Phase 8 — per-language base image).
# Untrusted repo code runs here: no secrets, no egress, non-root, capped.
# Toolchain baseline: PHP CLI + Composer + PHPUnit.
#
# Build: docker build -t bugfix-sandbox-php:latest -f docker/sandbox.php.Dockerfile .
FROM php:8.3-cli-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep unzip git \
    && rm -rf /var/lib/apt/lists/* \
    && curl -sS https://getcomposer.org/installer | php -- \
        --install-dir=/usr/local/bin --filename=composer

ENV COMPOSER_HOME=/tmp/composer COMPOSER_CACHE_DIR=/tmp/composer-cache
ENV PATH="/workspace/vendor/bin:${PATH}"

RUN useradd --create-home --uid 10001 sandbox
USER sandbox
WORKDIR /workspace

CMD ["php", "--version"]
