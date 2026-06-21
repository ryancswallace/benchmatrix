# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.11.21

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv-bin

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:/usr/local/bin:${PATH}"     PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     UV_LINK_MODE=copy

LABEL org.opencontainers.image.source="https://github.com/ryancswallace/benchmatrix"       org.opencontainers.image.licenses="MIT"       org.opencontainers.image.description="pytest-benchmark matrix utilities and result parsing"

WORKDIR /app

COPY --from=uv-bin /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src

RUN groupadd --system benchmatrix     && useradd --system --gid benchmatrix --home-dir /app --shell /usr/sbin/nologin benchmatrix     && uv sync --locked --no-dev --no-editable     && chown -R benchmatrix:benchmatrix /app

USER benchmatrix

CMD ["python", "-c", "from benchmatrix import BenchmarkCase; print(BenchmarkCase.__name__)"]

FROM runtime AS test

USER root

COPY . .

RUN uv sync --locked     && chown -R benchmatrix:benchmatrix /app

USER benchmatrix

CMD ["python", "-m", "pytest", "-q"]
