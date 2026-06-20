SHELL := /bin/sh

MAKEFLAGS += --no-print-directory

# Make uv available immediately after the standalone installer runs
export PATH := $(HOME)/.local/bin:$(HOME)/.cargo/bin:$(PATH)

UV_INSTALL_URL ?= https://astral.sh/uv/install.sh
NODE_MODULES_STAMP := node_modules/.package-lock.json
SBOM_PATH ?= dist/benchmatrix.cdx.json

.PHONY: help bootstrap npm-install ready install hooks-install lock-check test typecheck lint markdownlint workflow-lint spellcheck secrets security deps audit sbom build format check clean precommit fresh-precommit

help:
	@echo "Available targets:"
	@echo "  bootstrap         Install uv if it is not already available"
	@echo "  npm-install       Install Node development dependencies"
	@echo "  install           Sync Python dependencies from uv.lock"
	@echo "  hooks-install     Install pre-commit and pre-push Git hooks"
	@echo "  lock-check        Verify pyproject.toml and uv.lock are in sync"
	@echo "  format            Format code and apply Ruff auto-fixes"
	@echo "  clean             Remove local cache files"
	@echo "  test              Run unit tests"
	@echo "  typecheck         Run basedpyright type checks"
	@echo "  lint              Run Ruff lint and formatting checks"
	@echo "  markdownlint      Lint Markdown files"
	@echo "  workflow-lint     Lint GitHub Actions workflow files"
	@echo "  spellcheck        Run CSpell spell checks"
	@echo "  secrets           Scan tracked files for secrets"
	@echo "  security          Run Bandit security checks"
	@echo "  deps              Run deptry dependency checks"
	@echo "  audit             Audit locked dependencies for known vulnerabilities"
	@echo "  sbom              Generate a CycloneDX runtime dependency SBOM"
	@echo "  build             Build and validate distributions"
	@echo "  check             Run the full local validation suite"
	@echo "  ready             Sync dependencies and verify the environment"
	@echo "  precommit         Run all pre-commit hooks against all files"
	@echo "  fresh-precommit   Clean caches, install dependencies, run hooks and checks"

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

npm-install: $(NODE_MODULES_STAMP)

$(NODE_MODULES_STAMP): package.json package-lock.json
	@if ! command -v npm >/dev/null 2>&1; then \
		echo "npm is not installed."; \
		echo "Install Node.js/npm, then rerun this target."; \
		exit 1; \
	fi
	npm ci

install: bootstrap
	uv sync --locked

hooks-install: install npm-install
	uv run pre-commit install --install-hooks

lock-check: bootstrap
	uv lock --check

format: bootstrap
	uv run ruff check --fix .
	uv run ruff format .

clean:
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type d -name ".pytest_cache" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type d -name ".ruff_cache" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type d -name ".basedpyright_cache" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type d -name ".pyright" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type d -name "htmlcov" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type f -name ".coverage" -exec rm -f {} +

test: bootstrap
	uv run pytest -q

typecheck: bootstrap
	uv run basedpyright

lint: bootstrap
	uv run ruff check .
	uv run ruff format --check .

markdownlint: npm-install
	npx markdownlint-cli2

workflow-lint: install
	uv run pre-commit run actionlint --files $$(find .github/workflows -type f \( -name '*.yml' -o -name '*.yaml' \))

spellcheck: npm-install
	npx cspell .

secrets: install  # pragma: allowlist secret
	uv run detect-secrets-hook --baseline .secrets.baseline --no-verify --cores 1 $$(git ls-files --cached --others --exclude-standard ':!:package-lock.json' ':!:uv.lock' ':!:notebooks/demo.ipynb')  # pragma: allowlist secret

security: bootstrap
	uv run bandit -q -c pyproject.toml -r src examples

deps: bootstrap
	uv run deptry src examples

audit: bootstrap
	@audit_file=$$(mktemp); \
	trap 'rm -f "$$audit_file"' 0 1 2 15; \
	uv export --quiet --locked --all-groups --no-emit-project --format requirements-txt --output-file "$$audit_file" && \
	uv run pip-audit --requirement "$$audit_file" --require-hashes --disable-pip --strict --progress-spinner off

sbom: bootstrap
	@sbom_env=$$(mktemp -d); \
	trap 'rm -rf "$$sbom_env"' 0 1 2 15; \
	mkdir -p "$$(dirname "$(SBOM_PATH)")"; \
	uv venv --quiet "$$sbom_env" && \
	VIRTUAL_ENV="$$sbom_env" uv sync --quiet --locked --no-dev --active && \
	uv run cyclonedx-py environment "$$sbom_env/bin/python" --pyproject pyproject.toml --mc-type library \
		--output-reproducible --spec-version 1.6 --output-format JSON --output-file "$(SBOM_PATH)"

build: bootstrap
	uv build --clear
	uv run twine check dist/*
	$(MAKE) sbom

check: bootstrap
	@status=0; \
	echo "==> uv lockfile"; \
	uv lock --check || status=$$?; \
	echo ""; \
	echo "==> Ruff linting"; \
	uv run ruff check . || status=$$?; \
	uv run ruff format --check . || status=$$?; \
	echo ""; \
	echo "==> Markdown linting"; \
	$(MAKE) markdownlint || status=$$?; \
	echo ""; \
	echo "==> GitHub Actions workflow linting"; \
	$(MAKE) workflow-lint || status=$$?; \
	echo ""; \
	echo "==> CSpell spell checks"; \
	$(MAKE) spellcheck || status=$$?; \
	echo ""; \
	echo "==> Secret scanning"; \
	$(MAKE) secrets || status=$$?; \
	echo ""; \
	echo "==> Bandit security checks"; \
	uv run bandit -q -c pyproject.toml -r src examples || status=$$?; \
	echo ""; \
	echo "==> deptry dependency checks"; \
	uv run deptry src examples || status=$$?; \
	echo ""; \
	echo "==> pip-audit dependency vulnerabilities"; \
	$(MAKE) audit || status=$$?; \
	echo ""; \
	echo "==> Pytest unit tests"; \
	uv run pytest -q || status=$$?; \
	echo ""; \
	echo "==> basedpyright type checks"; \
	uv run basedpyright || status=$$?; \
	echo ""; \
	echo "==> Distribution build"; \
	uv build --clear || status=$$?; \
	uv run twine check dist/* || status=$$?; \
	echo ""; \
	echo "==> CycloneDX SBOM"; \
	$(MAKE) sbom || status=$$?; \
	exit $$status

ready:
	@for step in install check; do \
		if ! $(MAKE) $$step; then \
			echo "Environment setup failed during $$step."; \
			exit 1; \
		fi; \
	done; \
	echo ""; \
	echo "Environment is ready."

precommit: install npm-install
	uv run pre-commit run --all-files

fresh-precommit:
	@for step in clean install npm-install precommit check; do \
		if ! $(MAKE) $$step; then \
			echo ""; \
			echo "Fresh precommit failed during $$step."; \
			exit 1; \
		fi; \
	done; \
	echo ""; \
	echo "Fresh precommit completed successfully."
