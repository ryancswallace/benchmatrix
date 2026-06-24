FROM mcr.microsoft.com/devcontainers/python:3.14-bookworm

# The base image may include a Yarn APT source with a stale/missing key.
# Remove it because this project does not need Yarn from dl.yarnpkg.com.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap ripgrep \
    && rm -rf /var/lib/apt/lists/*
