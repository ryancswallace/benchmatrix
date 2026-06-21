SHELL := /bin/sh

MAKEFLAGS += --no-print-directory

# Make uv available immediately after the standalone installer runs
export PATH := $(HOME)/.local/bin:$(HOME)/.cargo/bin:$(PATH)

DOCKER ?= docker
DOCKER_SOCKET ?= /var/run/docker.sock
IMAGE_NAME ?= ghcr.io/ryancswallace/benchmatrix
IMAGE_TAG ?= local
TEST_IMAGE_NAME ?= ghcr.io/ryancswallace/benchmatrix-test
TRIVY_IMAGE ?= docker.io/aquasec/trivy:0.67.2
LINKCHECK_REPORT ?= reports/linkchecker.xml
MIN_DEPS_PYTHON ?= 3.11
NOX_ARGS ?=
PRECOMMIT_ARGS ?= --all-files
PYTEST_ARGS ?= -q
RUFF_ARGS ?= .
NODE_MODULES_STAMP := node_modules/.package-lock.json
SBOM_PATH ?= dist/benchmatrix.cdx.json
UV_INSTALL_URL ?= https://astral.sh/uv/install.sh

.PHONY: help bootstrap npm-install ready install hooks-install lock-check test test-min-deps test-matrix typecheck lint markdownlint docs docs-linkcheck serve-docs docker-lint docker-ready docker-build docker-build-test docker-test docker-smoke docker-scan docker-check workflow-lint spellcheck secrets security deps audit sbom smoke-dist build format check check-all ca clean clean-build precommit fresh-precommit

help:
	@echo "Available targets:"
	@echo "  bootstrap         Install uv if it is not already available"
	@echo "  npm-install       Install Node development dependencies"
	@echo "  install           Sync Python dependencies from uv.lock"
	@echo "  hooks-install     Install pre-commit and pre-push Git hooks"
	@echo "  lock-check        Verify pyproject.toml and uv.lock are in sync"
	@echo "  format            Format code and apply Ruff auto-fixes"
	@echo "  clean             Remove local cache files"
	@echo "  clean-build       Remove build and distribution artifacts"
	@echo "  test              Run unit tests"
	@echo "  test-min-deps     Run tests with minimum direct dependency versions"
	@echo "  test-matrix       Run the full local nox test and quality matrix"
	@echo "  typecheck         Run basedpyright type checks"
	@echo "  lint              Run Ruff lint and formatting checks"
	@echo "  docs              Build the documentation site"
	@echo "  docs-linkcheck    Check links in the built documentation site"
	@echo "  serve-docs        Serve the documentation site locally"
	@echo "  docker-lint       Lint Dockerfiles"
	@echo "  docker-build      Build the runtime Docker image"
	@echo "  docker-build-test Build the test Docker image"
	@echo "  docker-test       Build and run the test Docker image"
	@echo "  docker-smoke      Smoke-test the runtime Docker image"
	@echo "  docker-scan       Scan Docker images for critical vulnerabilities"
	@echo "  docker-check      Run Docker lint, build, test, smoke, and scan checks"
	@echo "  markdownlint      Lint Markdown files"
	@echo "  workflow-lint     Lint GitHub Actions workflow files"
	@echo "  spellcheck        Run CSpell spell checks"
	@echo "  secrets           Scan tracked files for secrets"
	@echo "  security          Run Bandit security checks"
	@echo "  deps              Run deptry dependency checks"
	@echo "  audit             Audit locked dependencies for known vulnerabilities"
	@echo "  sbom              Generate a CycloneDX runtime dependency SBOM"
	@echo "  smoke-dist        Install and import-test the built wheel"
	@echo "  build             Build, validate, smoke-test, and generate release artifacts"
	@echo "  check             Run the full local validation suite"
	@echo "  check-all         Run every local, matrix, hook, and Docker check"
	@echo "  ca                Alias for check-all"
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
	uv run ruff check --fix $(RUFF_ARGS)
	uv run ruff format $(RUFF_ARGS)

clean:
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type d -name ".pytest_cache" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type d -name ".ruff_cache" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type d -name ".basedpyright_cache" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type d -name ".pyright" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type d -name "htmlcov" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type f -name ".coverage" -exec rm -f {} +
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type d -name "site" -prune -exec rm -rf {} +
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type d -name "reports" -prune -exec rm -rf {} +

clean-build:
	rm -rf build dist
	find . -path "./.venv" -prune -o -path "./node_modules" -prune -o -type d -name "*.egg-info" -prune -exec rm -rf {} +

test: bootstrap
	uv run pytest $(PYTEST_ARGS)

test-min-deps: bootstrap
	uv run --python "$(MIN_DEPS_PYTHON)" --isolated --resolution lowest-direct --no-default-groups --group test --group release python -m pytest $(PYTEST_ARGS)

test-matrix: install
	uv run nox $(NOX_ARGS)

typecheck: bootstrap
	uv run basedpyright

lint: bootstrap
	uv run ruff check $(RUFF_ARGS)
	uv run ruff format --check $(RUFF_ARGS)

markdownlint: npm-install
	npx markdownlint-cli2

docs: install
	DISABLE_MKDOCS_2_WARNING=true uv run mkdocs build --strict

docs-linkcheck: docs
	mkdir -p "$$(dirname "$(LINKCHECK_REPORT)")"
	uv run linkchecker --no-status --no-warnings --ignore-url 'sitemap\.xml\.gz$$' -F xml/utf-8/"$(LINKCHECK_REPORT)" site/index.html

serve-docs: install
	DISABLE_MKDOCS_2_WARNING=true uv run mkdocs serve --strict

docker-lint: npm-install
	npx dockerfile-utils lint Dockerfile .devcontainer/Dockerfile

docker-ready:
	@if ! command -v "$(DOCKER)" >/dev/null 2>&1; then \
		echo "Docker CLI not found."; \
		exit 1; \
	fi
	@if ! "$(DOCKER)" info >/dev/null 2>&1; then \
		echo "Docker daemon is not reachable. Start Docker on the host and check devcontainer socket forwarding."; \
		exit 1; \
	fi

docker-build: docker-ready
	$(DOCKER) build --target runtime --tag "$(IMAGE_NAME):$(IMAGE_TAG)" .

docker-build-test: docker-ready
	$(DOCKER) build --target test --tag "$(TEST_IMAGE_NAME):$(IMAGE_TAG)" .

docker-test: docker-build-test
	$(DOCKER) run --rm "$(TEST_IMAGE_NAME):$(IMAGE_TAG)"

docker-smoke: docker-build
	$(DOCKER) run --rm "$(IMAGE_NAME):$(IMAGE_TAG)"

docker-scan: docker-build docker-build-test
	@if command -v trivy >/dev/null 2>&1; then \
		trivy image --ignore-unfixed --severity CRITICAL --exit-code 1 "$(IMAGE_NAME):$(IMAGE_TAG)" && \
		trivy image --ignore-unfixed --severity CRITICAL --exit-code 1 "$(TEST_IMAGE_NAME):$(IMAGE_TAG)"; \
	else \
		$(DOCKER) run --rm -v "$(DOCKER_SOCKET):/var/run/docker.sock" "$(TRIVY_IMAGE)" image --ignore-unfixed --severity CRITICAL --exit-code 1 "$(IMAGE_NAME):$(IMAGE_TAG)" && \
		$(DOCKER) run --rm -v "$(DOCKER_SOCKET):/var/run/docker.sock" "$(TRIVY_IMAGE)" image --ignore-unfixed --severity CRITICAL --exit-code 1 "$(TEST_IMAGE_NAME):$(IMAGE_TAG)"; \
	fi

docker-check: docker-lint docker-test docker-smoke docker-scan

workflow-lint: install
	uv run pre-commit run actionlint --files $$(find .github/workflows -type f \( -name '*.yml' -o -name '*.yaml' \))
	uv run zizmor --min-severity medium .github/workflows

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

smoke-dist: bootstrap
	@smoke_env=$$(mktemp -d); \
	trap 'rm -rf "$$smoke_env"' 0 1 2 15; \
	wheel=$$(find dist -maxdepth 1 -type f -name '*.whl' | sort | head -n 1); \
	if [ -z "$$wheel" ]; then \
		echo "No wheel found in dist/. Run make build first."; \
		exit 1; \
	fi; \
	uv venv --quiet "$$smoke_env" && \
	VIRTUAL_ENV="$$smoke_env" uv pip install --quiet "$$wheel" && \
	"$$smoke_env/bin/python" -c "from benchmatrix import BenchmarkCase; print(BenchmarkCase.__name__)"

build: bootstrap
	uv build --clear
	uv run twine check dist/*
	$(MAKE) smoke-dist
	$(MAKE) sbom

check: bootstrap
	@status=0; \
	echo "==> uv lockfile"; \
	$(MAKE) lock-check || status=$$?; \
	echo ""; \
	echo "==> Python linting and formatting"; \
	$(MAKE) lint || status=$$?; \
	echo ""; \
	echo "==> Python type checks"; \
	$(MAKE) typecheck || status=$$?; \
	echo ""; \
	echo "==> Pytest unit tests"; \
	$(MAKE) test || status=$$?; \
	echo ""; \
	echo "==> Dependency usage checks"; \
	$(MAKE) deps || status=$$?; \
	echo ""; \
	echo "==> Markdown linting"; \
	$(MAKE) markdownlint || status=$$?; \
	echo ""; \
	echo "==> Dockerfile linting"; \
	$(MAKE) docker-lint || status=$$?; \
	echo ""; \
	echo "==> GitHub Actions workflow linting"; \
	$(MAKE) workflow-lint || status=$$?; \
	echo ""; \
	echo "==> CSpell spell checks"; \
	$(MAKE) spellcheck || status=$$?; \
	echo ""; \
	echo "==> Documentation site and links"; \
	$(MAKE) docs-linkcheck || status=$$?; \
	echo ""; \
	echo "==> Secret scanning"; \
	$(MAKE) secrets || status=$$?; \
	echo ""; \
	echo "==> Bandit security checks"; \
	$(MAKE) security || status=$$?; \
	echo ""; \
	echo "==> pip-audit dependency vulnerabilities"; \
	$(MAKE) audit || status=$$?; \
	echo ""; \
	echo "==> Minimum dependency tests"; \
	$(MAKE) test-min-deps || status=$$?; \
	echo ""; \
	echo "==> Distribution build, smoke test, and SBOM"; \
	$(MAKE) build || status=$$?; \
	echo ""; \
	echo "============================================================"; \
	if [ "$$status" -eq 0 ]; then \
		echo "ALL CHECKS PASSED"; \
	else \
		echo "CHECKS FAILED (exit $$status)"; \
	fi; \
	echo "============================================================"; \
	exit $$status

check-all: bootstrap
	@status=0; \
	echo "==> Standard validation suite"; \
	$(MAKE) check || status=$$?; \
	echo ""; \
	echo "==> Full pre-commit hook suite"; \
	$(MAKE) precommit || status=$$?; \
	echo ""; \
	echo "==> Full nox test and quality matrix"; \
	$(MAKE) test-matrix || status=$$?; \
	echo ""; \
	echo "==> Full Docker validation suite"; \
	$(MAKE) docker-check || status=$$?; \
	echo ""; \
	echo "============================================================"; \
	if [ "$$status" -eq 0 ]; then \
		echo "ALL AVAILABLE CHECKS PASSED"; \
	else \
		echo "CHECK-ALL FAILED (exit $$status)"; \
	fi; \
	echo "============================================================"; \
	exit $$status

ca: check-all

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
	uv run pre-commit run $(PRECOMMIT_ARGS)

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
