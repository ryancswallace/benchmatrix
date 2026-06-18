# benchkit project instructions

## Project

This repository contains `benchkit`, a small Python package that provides utilities for building pytest-benchmark benchmark matrices and parsing pytest-benchmark JSON output.

## Package layout

- `src/benchkit/__init__.py`: public package exports
- `src/benchkit/_schema.py`: private shared schema constants
- `src/benchkit/exceptions.py`: package-specific exceptions
- `src/benchkit/bench_harness.py`: pytest-benchmark harness utilities
- `src/benchkit/bench_results.py`: pytest-benchmark JSON parsing/display utilities
- `tests/`: tests

## Tooling

Use uv. The authoritative local check command is:

```bash
make check
```

It runs Ruff (`make lint`), pytest (`make test`), and basedpyright (`make typetest`). Run it after edits.

Useful commands:

```bash
make format
make lint
make test
make typecheck
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

- Preserve the public API exported from `benchkit.__init__` unless explicitly asked to change it or required to resolve an issue most cleanly.
- Keep `_schema.py` package-private.
- Keep result parsing exceptions package-specific.
- Keep metadata strict-JSON-safe.
- Target functions under test are synchronous only; async functions are unsupported.
