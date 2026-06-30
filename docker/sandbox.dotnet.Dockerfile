# .NET execution sandbox (Phase 8 — per-language base image).
# Untrusted repo code runs here: no secrets, no egress, non-root, capped.
# Toolchain baseline: the .NET SDK (`dotnet test`; xUnit/NUnit/MSTest).
#
# Build: docker build -t bugfix-sandbox-dotnet:latest -f docker/sandbox.dotnet.Dockerfile .
FROM mcr.microsoft.com/dotnet/sdk:8.0-jammy

RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Keep telemetry off and caches on writable, user-owned paths.
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 \
    NUGET_PACKAGES=/tmp/nuget HOME=/tmp

RUN useradd --create-home --uid 10001 sandbox
USER sandbox
WORKDIR /workspace

CMD ["dotnet", "--info"]
