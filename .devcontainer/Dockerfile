FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# The base image may include a Yarn APT source with a stale/missing key.
# Remove it because this project does not need Yarn from dl.yarnpkg.com.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends ripgrep \
    && rm -rf /var/lib/apt/lists/*