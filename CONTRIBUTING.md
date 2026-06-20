# Contributing to benchmatrix

Thanks for considering a contribution.

## Before you start

For substantial changes, open an issue first so the problem and proposed
direction can be discussed. Small fixes and documentation improvements can go
directly to a pull request.

By participating, you agree to follow the [code of conduct](CODE_OF_CONDUCT.md).
Please report security vulnerabilities through the process in
[SECURITY.md](SECURITY.md), not through a public issue.

## Development

benchmatrix requires Python 3.11 or newer and uses
[uv](https://docs.astral.sh/uv/) for Python dependency management.

Set up and verify the development environment:

```bash
make ready
make hooks-install
```

Before submitting a change, run:

```bash
make format
make check
```

`make check` verifies the uv lockfile, Ruff formatting and linting, Markdown,
GitHub Actions workflows, CSpell, secret scanning, Bandit, deptry, pip-audit,
pytest and coverage, basedpyright, and built distributions, including CycloneDX
SBOM generation. New behavior should include tests, and public APIs should
include Google-style docstrings.

The Git hooks run fast, file-oriented checks. Use `make precommit` to run every
hook manually. Treat additions to `.secrets.baseline` as security-sensitive
changes and review each detected value before updating the baseline.

## Pull requests

Keep each pull request focused on one coherent change. In the description:

* explain the problem and the chosen approach;
* identify any public API or compatibility impact;
* include tests for behavior changes;
* update documentation and `CHANGELOG.md` when users will notice the change.

Maintainers may request changes before merging. Contributions are accepted
under the project's [MIT License](LICENSE).
