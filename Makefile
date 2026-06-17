SHELL := /bin/sh

# Make uv available immediately after the standalone installer runs
export PATH := $(HOME)/.local/bin:$(HOME)/.cargo/bin:$(PATH)

UV_INSTALL_URL ?= https://astral.sh/uv/install.sh

.PHONY: help bootstrap ready install test typecheck lint format check clean

help:
	@echo "Available targets:"
	@echo "  bootstrap	Install uv if it is not already available"
	@echo "  ready		Sync dependencies and verify the environment"
	@echo "  install	Sync dependencies from uv.lock"
	@echo "  test		Run unit tests"
	@echo "  typecheck	Run basedpyright type checks"
	@echo "  lint		Run Ruff linting checks"
	@echo "  format		Format code and apply Ruff auto-fixes"
	@echo "  check		Run lint, tests, and type checks"
	@echo "  clean		Remove local cache files"

bootstrap:
	@if command -v uv >/dev/null 2>&1; then \
		uv --version; \
	else \
		echo "uv not found; installing uv with the official standalone installer."; \
		if command -v curl >/dev/null 2>&1; then \
			curl -LsSf "$(UV_INSTALL_URL)" | sh; \
		elif command -v wget >/dev/null 2>&1; then \
			wget -qO- "$(UV_INSTALL_URL)" | sh; \
		else \
			echo "Neither curl nor wget is installed."; \
			echo "Install uv manually, then rerun: make ready"; \
			exit 1; \
		fi; \
		uv --version; \
	fi

ready: install check
	@echo "Environment is ready."

install: bootstrap
	uv sync --locked

test: bootstrap
	uv run pytest -q

typecheck: bootstrap
	uv run basedpyright src/ tests/

lint: bootstrap
	uv run ruff check .

format: bootstrap
	uv run ruff format .
	uv run ruff check --fix .

check: bootstrap
	@status=0; \
	echo "==> Ruff linting"; \
	uv run ruff check . || status=$$?; \
	echo "\n==> Pytest unit tests"; \
	uv run pytest -q || status=$$?; \
	echo "\n==> basedpyright type checks"; \
	uv run basedpyright src/ tests/ || status=$$?; \
	exit $$status

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -prune -exec rm -rf {} +