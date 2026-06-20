# Dependency policy

Keep runtime dependencies small and justified. benchmatrix currently depends on
pytest and pytest-benchmark because it is a pytest-benchmark integration layer.

## Runtime dependencies

Add a runtime dependency only when it is needed by installed users. Prefer the
standard library for small utilities.

## Development dependencies

Development dependencies are split by concern in `pyproject.toml`:

* `test` for pytest support and test-only libraries;
* `lint` for Ruff and pre-commit orchestration;
* `type` for basedpyright;
* `docs` for MkDocs and API documentation generation;
* `security` for Bandit, deptry, detect-secrets, and pip-audit;
* `release` for build, Twine, and SBOM tooling;
* `automation` for nox.

The `dev` group includes all focused groups, so the default `uv sync --locked`
workflow still installs the complete local development environment. Tooling
should not overlap without a clear reason.

## Updates

Dependency updates should include:

1. lockfile update;
2. `make check`;
3. `make test-matrix` when compatibility may be affected;
4. changelog entry when users or maintainers need to know.

Dependabot opens routine weekly update pull requests for Python, Node,
pre-commit, GitHub Actions, Docker, and devcontainer dependencies. Review those
pull requests like any other dependency change: confirm the scope is expected,
let CI finish, and require a human merge decision.

Minor and patch updates are grouped where Dependabot supports grouping. Major
updates are intentionally left as separate pull requests so compatibility and
security implications are easier to review.

## Vulnerabilities

pip-audit failures should be triaged by severity, exploitability, and whether the
affected dependency is runtime or development-only. See the dependency-update and
security-report runbooks for operational steps.
