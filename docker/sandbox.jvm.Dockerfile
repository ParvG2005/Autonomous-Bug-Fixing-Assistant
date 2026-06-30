# JVM execution sandbox (Phase 8 — per-language base image).
# Untrusted repo code runs here: no secrets, no egress, non-root, capped.
# Toolchain baseline: JDK 21 + Maven + Gradle (Java/Kotlin).
#
# Build: docker build -t bugfix-sandbox-jvm:latest -f docker/sandbox.jvm.Dockerfile .
FROM eclipse-temurin:21-jdk-jammy

RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep maven gradle \
    && rm -rf /var/lib/apt/lists/*

# Local repo/caches on writable paths the non-root user owns.
ENV MAVEN_OPTS="-Dmaven.repo.local=/tmp/m2" GRADLE_USER_HOME=/tmp/gradle

RUN useradd --create-home --uid 10001 sandbox
USER sandbox
WORKDIR /workspace

CMD ["java", "-version"]
