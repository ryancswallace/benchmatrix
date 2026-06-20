# Development

## Setup

```bash
make ready
make hooks-install
```

Use uv for Python dependency management. Outside the devcontainer, install
Node.js and npm so Markdown and spelling checks can run.

## Daily loop

```bash
make format
make check
```

Use focused commands while iterating:

```bash
make test
make lint
make typecheck
make docs
```

Run the broader local matrix before changes that may vary by interpreter:

```bash
make test-matrix
```

## Documentation loop

Edit files under `docs/`, then run:

```bash
make docs
```

API reference pages are generated from docstrings, so update package docstrings
when public behavior changes.
