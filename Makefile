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
RELEASE_VERSION ?= $(BENCHMATRIX_RELEASE_VERSION)
RELEASE_PR_BASE ?= main
RELEASE_PR_FLAGS ?=
RELEASE_TAG_BASE ?= main

# -----------------------------------------------------------------------------
# Target declarations
# -----------------------------------------------------------------------------
.PHONY: help all
.PHONY: bootstrap npm-install install hooks-install ready
.PHONY: clean clean-build
.PHONY: format lint typecheck markdownlint workflow-lint workflow-env-lint spellcheck
.PHONY: test test-min-deps test-matrix
.PHONY: docs docs-linkcheck serve-docs
.PHONY: docker-lint docker-ready docker-build docker-build-test docker-test docker-smoke docker-scan docker-check
.PHONY: lock-check deps secrets security audit
.PHONY: release-version-check release-preflight prepare-release release-pr-ready release-pr release-tag sbom smoke-dist validate-dist build
.PHONY: check check-all ca precommit prepush fresh-precommit

# -----------------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------------
help:
	@echo "Available targets:"
	@echo ""
	@echo "Setup:"
	@echo "  bootstrap             Install uv if it is not already available"
	@echo "  npm-install           Install Node development dependencies"
	@echo "  install               Sync Python dependencies from uv.lock"
	@echo "  hooks-install         Install pre-commit and pre-push Git hooks"
	@echo "  ready                 Sync dependencies and verify the environment"
	@echo ""
	@echo "Cleanup:"
	@echo "  clean                 Remove local cache files"
	@echo "  clean-build           Remove build and distribution artifacts"
	@echo ""
	@echo "Python quality:"
	@echo "  format                Format code and apply Ruff auto-fixes"
	@echo "  lint                  Run Ruff lint and formatting checks"
	@echo "  typecheck             Run basedpyright type checks"
	@echo ""
	@echo "Tests:"
	@echo "  test                  Run unit tests"
	@echo "  test-min-deps         Run tests with minimum direct dependency versions"
	@echo "  test-matrix           Run the full local nox test and quality matrix"
	@echo ""
	@echo "Documentation:"
	@echo "  docs                  Build the documentation site"
	@echo "  docs-linkcheck        Check links in the built documentation site"
	@echo "  serve-docs            Serve the documentation site locally"
	@echo ""
	@echo "Docker:"
	@echo "  docker-lint           Lint Dockerfiles"
	@echo "  docker-build          Build the runtime Docker image"
	@echo "  docker-build-test     Build the test Docker image"
	@echo "  docker-test           Build and run the test Docker image"
	@echo "  docker-smoke          Smoke-test the runtime Docker image"
	@echo "  docker-scan           Scan Docker images for critical vulnerabilities"
	@echo "  docker-check          Run Docker lint, build, test, smoke, and scan checks"
	@echo ""
	@echo "Repository quality:"
	@echo "  markdownlint          Lint Markdown files"
	@echo "  workflow-lint         Lint GitHub Actions workflow files"
	@echo "  workflow-env-lint     Check referenced GitHub environments exist"
	@echo "  spellcheck            Run CSpell spell checks"
	@echo ""
	@echo "Dependencies and security:"
	@echo "  lock-check            Verify pyproject.toml and uv.lock are in sync"
	@echo "  deps                  Run deptry dependency checks"
	@echo "  secrets               Scan tracked files for secrets"
	@echo "  security              Run Bandit security checks"
	@echo "  audit                 Audit locked dependencies for known vulnerabilities"
	@echo ""
	@echo "Release artifacts:"
	@echo "  release-version-check Validate BENCHMATRIX_RELEASE_VERSION syntax"
	@echo "  release-preflight     Check release prerequisites before preparing a release"
	@echo "  prepare-release       Update release metadata; set BENCHMATRIX_RELEASE_VERSION=X.Y.Z"
	@echo "  release-pr-ready      Prepare, validate, commit, push, and open the release PR"
	@echo "  release-pr            Commit, push, and open the release pull request"
	@echo "  release-tag           Create and push the annotated release tag"
	@echo "  sbom                  Generate a CycloneDX runtime dependency SBOM"
	@echo "  smoke-dist            Install and import-test the built wheel"
	@echo "  validate-dist         Verify dist contains the expected release artifacts"
	@echo "  build                 Build, validate, smoke-test, and generate release artifacts"
	@echo ""
	@echo "Validation suites:"
	@echo "  all                   Alias for check"
	@echo "  check                 Run the full local validation suite"
	@echo "  check-all             Run every local, matrix, hook, and Docker check"
	@echo "  ca                    Alias for check-all"
	@echo "  precommit             Run pre-commit-stage hooks against all files"
	@echo "  prepush               Run pre-push-stage hooks"
	@echo "  fresh-precommit       Clean caches, install dependencies, run hooks and checks"

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------
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
	uv run pre-commit install --install-hooks --hook-type pre-commit --hook-type pre-push

ready:
	@for step in install check; do \
		if ! $(MAKE) $$step; then \
			echo "Environment setup failed during $$step."; \
			exit 1; \
		fi; \
	done; \
	echo ""; \
	echo "Environment is ready."

# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# Python quality
# -----------------------------------------------------------------------------
format: bootstrap
	uv run ruff check --fix $(RUFF_ARGS)
	uv run ruff format $(RUFF_ARGS)

lint: bootstrap
	uv run ruff check $(RUFF_ARGS)
	uv run ruff format --check $(RUFF_ARGS)

typecheck: bootstrap
	uv run basedpyright

# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------
test: bootstrap
	uv run pytest $(PYTEST_ARGS)

test-min-deps: bootstrap
	uv run --python "$(MIN_DEPS_PYTHON)" --isolated --resolution lowest-direct --no-default-groups --group test --group release python -m pytest $(PYTEST_ARGS)

test-matrix: install
	uv run nox $(NOX_ARGS)

# -----------------------------------------------------------------------------
# Documentation
# -----------------------------------------------------------------------------
docs: install
	DISABLE_MKDOCS_2_WARNING=true uv run mkdocs build --strict

docs-linkcheck: docs
	mkdir -p "$$(dirname "$(LINKCHECK_REPORT)")"
	uv run linkchecker --no-status --no-warnings --ignore-url 'sitemap\.xml\.gz$$' -F xml/utf-8/"$(LINKCHECK_REPORT)" site/index.html

serve-docs: install
	DISABLE_MKDOCS_2_WARNING=true uv run mkdocs serve --strict

# -----------------------------------------------------------------------------
# Docker
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# Repository quality
# -----------------------------------------------------------------------------
markdownlint: npm-install
	npx markdownlint-cli2

workflow-lint: install
	@if [ -d .github/workflows ]; then \
		workflow_files=$$(find .github/workflows -type f \( -name '*.yml' -o -name '*.yaml' \)); \
	else \
		workflow_files=""; \
	fi; \
	if [ -n "$$workflow_files" ]; then \
		uv run pre-commit run --hook-stage pre-commit actionlint --files $$workflow_files && \
		uv run pre-commit run --hook-stage pre-commit zizmor --files $$workflow_files; \
	else \
		echo "No GitHub Actions workflow files found; skipping workflow lint."; \
	fi

workflow-env-lint: npm-install
	npm run workflow-env-lint

spellcheck: npm-install
	npx cspell .

# -----------------------------------------------------------------------------
# Dependencies and security
# -----------------------------------------------------------------------------
lock-check: bootstrap
	uv lock --check

deps: bootstrap
	uv run deptry src examples

secrets: install  # pragma: allowlist secret
	uv run detect-secrets-hook --baseline .secrets.baseline --no-verify --cores 1 $$(git ls-files --cached --others --exclude-standard ':!:package-lock.json' ':!:uv.lock' ':!:notebooks/demo.ipynb')  # pragma: allowlist secret

security: bootstrap
	uv run bandit -q -c pyproject.toml -r src examples

audit: bootstrap
	@audit_file=$$(mktemp); \
	trap 'rm -f "$$audit_file"' 0 1 2 15; \
	uv export --quiet --locked --all-groups --no-emit-project --format requirements-txt --output-file "$$audit_file" && \
	uv run pip-audit --requirement "$$audit_file" --require-hashes --disable-pip --strict --progress-spinner off

# -----------------------------------------------------------------------------
# Release artifacts
# -----------------------------------------------------------------------------
release-version-check: bootstrap
	uv run python scripts/prepare_release.py validate-version "$(RELEASE_VERSION)"

release-preflight: release-version-check
	uv run python scripts/release_preflight.py "$(RELEASE_VERSION)" --base "$(RELEASE_PR_BASE)"

prepare-release: release-version-check
	uv run python scripts/prepare_release.py prepare "$(RELEASE_VERSION)" $(if $(RELEASE_DATE),--date "$(RELEASE_DATE)",)

release-pr-ready: release-version-check
	$(MAKE) release-preflight
	$(MAKE) prepare-release
	$(MAKE) check
	$(MAKE) release-pr

release-pr: release-version-check
	uv run python scripts/create_release_pr.py "$(RELEASE_VERSION)" --base "$(RELEASE_PR_BASE)" $(RELEASE_PR_FLAGS)

release-tag: release-version-check
	uv run python scripts/create_release_tag.py "$(RELEASE_VERSION)" --base "$(RELEASE_TAG_BASE)"
	@release_url=$$(gh repo view --json url --jq .url 2>/dev/null || \
		git config --get remote.origin.url | sed -E 's#^git@github.com:#https://github.com/#; s#\.git$$##'); \
	echo "GitHub Releases: $$release_url/releases"

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

validate-dist: bootstrap
	@version=$$(uv version --short); \
	expected_wheel="dist/benchmatrix-$$version-py3-none-any.whl"; \
	expected_sdist="dist/benchmatrix-$$version.tar.gz"; \
	expected_sbom="$(SBOM_PATH)"; \
	status=0; \
	for artifact in "$$expected_wheel" "$$expected_sdist" "$$expected_sbom"; do \
		if [ ! -f "$$artifact" ]; then \
			echo "Missing expected artifact: $$artifact"; \
			status=1; \
		fi; \
	done; \
	unexpected=$$(find dist -maxdepth 1 -type f ! -name ".gitignore" ! -name "benchmatrix-$$version-py3-none-any.whl" ! -name "benchmatrix-$$version.tar.gz" ! -name "$$(basename "$(SBOM_PATH)")" | sort); \
	if [ -n "$$unexpected" ]; then \
		echo "Unexpected files in dist/:"; \
		printf '%s\n' "$$unexpected"; \
		status=1; \
	fi; \
	if [ "$$status" -ne 0 ]; then \
		exit "$$status"; \
	fi; \
	echo "dist/ contains expected release artifacts for $$version."

build: bootstrap
	uv build --clear
	uv run twine check dist/*
	$(MAKE) smoke-dist
	$(MAKE) sbom
	$(MAKE) validate-dist

# -----------------------------------------------------------------------------
# Validation suites
# -----------------------------------------------------------------------------
all: check

check: bootstrap
	@status=0; \
	failed_targets=""; \
	echo "==> uv lockfile"; \
	$(MAKE) lock-check || { status=$$?; failed_targets="$$failed_targets lock-check"; }; \
	echo ""; \
	echo "==> Python linting and formatting"; \
	$(MAKE) lint || { status=$$?; failed_targets="$$failed_targets lint"; }; \
	echo ""; \
	echo "==> Python type checks"; \
	$(MAKE) typecheck || { status=$$?; failed_targets="$$failed_targets typecheck"; }; \
	echo ""; \
	echo "==> Pytest unit tests"; \
	$(MAKE) test || { status=$$?; failed_targets="$$failed_targets test"; }; \
	echo ""; \
	echo "==> Dependency usage checks"; \
	$(MAKE) deps || { status=$$?; failed_targets="$$failed_targets deps"; }; \
	echo ""; \
	echo "==> Markdown linting"; \
	$(MAKE) markdownlint || { status=$$?; failed_targets="$$failed_targets markdownlint"; }; \
	echo ""; \
	echo "==> Dockerfile linting"; \
	$(MAKE) docker-lint || { status=$$?; failed_targets="$$failed_targets docker-lint"; }; \
	echo ""; \
	echo "==> GitHub Actions workflow linting"; \
	$(MAKE) workflow-lint || { status=$$?; failed_targets="$$failed_targets workflow-lint"; }; \
	echo ""; \
	echo "==> CSpell spell checks"; \
	$(MAKE) spellcheck || { status=$$?; failed_targets="$$failed_targets spellcheck"; }; \
	echo ""; \
	echo "==> Documentation site and links"; \
	$(MAKE) docs-linkcheck || { status=$$?; failed_targets="$$failed_targets docs-linkcheck"; }; \
	echo ""; \
	echo "==> Secret scanning"; \
	$(MAKE) secrets || { status=$$?; failed_targets="$$failed_targets secrets"; }; \
	echo ""; \
	echo "==> Bandit security checks"; \
	$(MAKE) security || { status=$$?; failed_targets="$$failed_targets security"; }; \
	echo ""; \
	echo "==> pip-audit dependency vulnerabilities"; \
	$(MAKE) audit || { status=$$?; failed_targets="$$failed_targets audit"; }; \
	echo ""; \
	echo "==> Minimum dependency tests"; \
	$(MAKE) test-min-deps || { status=$$?; failed_targets="$$failed_targets test-min-deps"; }; \
	echo ""; \
	echo "==> Distribution build, smoke test, and SBOM"; \
	$(MAKE) build || { status=$$?; failed_targets="$$failed_targets build"; }; \
	echo ""; \
	echo "============================================================"; \
	if [ "$$status" -eq 0 ]; then \
		echo "ALL CHECKS PASSED"; \
	else \
		echo "CHECKS FAILED (exit $$status)"; \
		echo "Failed targets:"; \
		for target in $$failed_targets; do \
			echo "  - $$target"; \
		done; \
	fi; \
	echo "============================================================"; \
	exit $$status

check-all: bootstrap
	@status=0; \
	failed_targets=""; \
	echo "==> Standard validation suite"; \
	$(MAKE) check || { status=$$?; failed_targets="$$failed_targets check"; }; \
	echo ""; \
	echo "==> Full pre-commit hook suite"; \
	$(MAKE) precommit || { status=$$?; failed_targets="$$failed_targets precommit"; }; \
	echo ""; \
	echo "==> Full nox test and quality matrix"; \
	$(MAKE) test-matrix || { status=$$?; failed_targets="$$failed_targets test-matrix"; }; \
	echo ""; \
	echo "==> Full Docker validation suite"; \
	$(MAKE) docker-check || { status=$$?; failed_targets="$$failed_targets docker-check"; }; \
	echo ""; \
	echo "============================================================"; \
	if [ "$$status" -eq 0 ]; then \
		echo "ALL AVAILABLE CHECKS PASSED"; \
	else \
		echo "CHECK-ALL FAILED (exit $$status)"; \
		echo "Failed targets:"; \
		for target in $$failed_targets; do \
			echo "  - $$target"; \
		done; \
	fi; \
	echo "============================================================"; \
	exit $$status

ca: check-all

precommit: install npm-install
	uv run pre-commit run --hook-stage pre-commit $(PRECOMMIT_ARGS)

prepush: install npm-install
	uv run pre-commit run --hook-stage pre-push $(PRECOMMIT_ARGS)

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
