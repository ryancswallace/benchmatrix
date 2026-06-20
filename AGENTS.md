# benchmatrix project instructions

## Project

This repository contains `benchmatrix`, a small Python package that provides utilities for building pytest-benchmark benchmark matrices and parsing pytest-benchmark JSON output.

## Package layout

- `src/benchmatrix/__init__.py`: public package exports
- `src/benchmatrix/_schema.py`: private shared schema constants
- `src/benchmatrix/exceptions.py`: package-specific exceptions
- `src/benchmatrix/bench_harness.py`: pytest-benchmark harness utilities
- `src/benchmatrix/bench_results.py`: pytest-benchmark JSON parsing/display utilities
- `tests/`: tests

## Tooling

Use uv. The authoritative local check command is:

```bash
make check
```

It checks the uv lockfile, Ruff, Markdown, the documentation site, GitHub Actions
workflows, CSpell, secrets, Bandit, deptry, pip-audit, pytest and coverage,
basedpyright, built distributions, and CycloneDX SBOM generation. Run it after edits.

Useful commands:

```bash
make format
make lint
make markdownlint
make docs
make workflow-lint
make secrets
make test
make test-matrix
make typecheck
make security
make deps
make audit
make sbom
make build
make precommit
make check
```

## Code style

- Python 3.11+
- Type hints should pass basedpyright in normal mode.
- Use Ruff for linting and formatting.
- Public functions/classes use Google-style docstrings.
- Private helpers use concise one-line PEP 257 docstrings.
- Do not add broad `type: ignore`, `# noqa`, or pyright suppressions unless there is no cleaner alternative.

## API constraints

- Preserve the public API exported from `benchmatrix.__init__` unless explicitly asked to change it or required to resolve an issue most cleanly.
- Keep `_schema.py` package-private.
- Keep result parsing exceptions package-specific.
- Keep metadata strict-JSON-safe.
- Target functions under test are synchronous only; async functions are unsupported.
