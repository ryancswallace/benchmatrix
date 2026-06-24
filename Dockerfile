# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.11.21

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv-bin

FROM python:${PYTHON_VERSION}-slim-bookworm AS python-base

ARG APP_UID=10001
ARG APP_GID=10001

ENV PATH="/app/.venv/bin:/usr/local/bin:${PATH}" \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN groupadd --gid "${APP_GID}" benchmatrix \
    && useradd --uid "${APP_UID}" --gid benchmatrix --home-dir /app --shell /usr/sbin/nologin benchmatrix \
    && chown benchmatrix:benchmatrix /app

FROM python-base AS builder

COPY --from=uv-bin /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM python-base AS runtime

LABEL org.opencontainers.image.source="https://github.com/ryancswallace/benchmatrix" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.description="Build pytest-benchmark matrices and parse benchmark results with lightweight Python utilities."

COPY --from=builder --chown=benchmatrix:benchmatrix /app/.venv /app/.venv
COPY --chown=benchmatrix:benchmatrix README.md LICENSE ./

USER benchmatrix

CMD ["python", "-c", "from benchmatrix import BenchmarkCase; print(BenchmarkCase.__name__)"]

FROM builder AS test

COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked \
    && chown -R benchmatrix:benchmatrix /app

USER benchmatrix

CMD ["python", "-m", "pytest", "-q"]
