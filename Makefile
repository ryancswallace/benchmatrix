SHELL := /bin/sh

MAKEFLAGS += --no-print-directory

# Make uv available immediately after the standalone installer runs
export PATH := $(HOME)/.local/bin:$(HOME)/.cargo/bin:$(PATH)

UV_INSTALL_URL ?= https://astral.sh/uv/install.sh

.PHONY: help bootstrap ready install test typecheck lint format check clean precommit fresh-precommit

help:
	@echo "Available targets:"
	@echo "  bootstrap         Install uv if it is not already available"
	@echo "  install           Sync dependencies from uv.lock"
	@echo "  format            Format code and apply Ruff auto-fixes"
	@echo "  clean             Remove local cache files"
	@echo "  test              Run unit tests"
	@echo "  typecheck         Run basedpyright type checks"
	@echo "  lint              Run Ruff linting checks"
	@echo "  check             Run lint, tests, and type checks"
	@echo "  ready             Sync dependencies and verify the environment"
	@echo "  precommit         Install dependencies, auto-format/fix, then run checks"
	@echo "  fresh-precommit   Clean caches, install dependencies, auto-format/fix, then run checks"

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

install: bootstrap
	uv sync --locked

format: bootstrap
	uv run ruff check --fix .
	uv run ruff format .

clean:
	find . -path "./.venv" -prune -o -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -type d -name ".pytest_cache" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -type d -name ".ruff_cache" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -type d -name ".basedpyright_cache" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -type d -name ".pyright" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -type d -name "htmlcov" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -type f -name ".coverage" -delete

test: bootstrap
	uv run pytest -q

typecheck: bootstrap
	uv run basedpyright src/ tests/

lint: bootstrap
	uv run ruff check .

check: bootstrap
	@status=0; \
	echo "==> Ruff linting"; \
	uv run ruff check . || status=$$?; \
	echo ""; \
	echo "==> Pytest unit tests"; \
	uv run pytest -q || status=$$?; \
	echo ""; \
	echo "==> basedpyright type checks"; \
	uv run basedpyright src/ tests/ || status=$$?; \
	exit $$status

ready:
	@$(MAKE) install
	@$(MAKE) check
	@echo "Environment is ready."

precommit:
	@$(MAKE) install
	@$(MAKE) format
	@$(MAKE) check

fresh-precommit:
	@$(MAKE) clean
	@$(MAKE) install
	@$(MAKE) format
	@$(MAKE) check