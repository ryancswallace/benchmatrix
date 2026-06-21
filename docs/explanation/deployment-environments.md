# Deployment environments

benchmatrix has two deployment-like outputs: Python distributions and the
documentation site.

## Python package

Build artifacts are created under `dist/` and validated with Twine:

```bash
make build
```

The release workflow publishes from the `pypi` environment with PyPI Trusted
Publishing and OIDC. Do not add a long-lived PyPI token unless Trusted
Publishing is temporarily blocked.

## Docker images

The Docker workflow builds separate runtime and test images. Pull requests build
and scan images without publishing them. Pushes to `main` and release tags that
match `v*` publish images to GitHub Container Registry.

The devcontainer uses Docker-outside-of-Docker so maintainers can run Docker
checks locally against the host Docker daemon after rebuilding the devcontainer.
Normal local validation still avoids Docker image builds; `make check` only lints
Dockerfiles.

## Documentation site

Build the site locally with:

```bash
make docs
```

The generated output lives under `site/`. The documentation workflow builds docs
for pull requests and deploys from `main` through GitHub Pages with minimal
permissions and the `github-pages` environment.

## GitHub Actions environments

Recommended external environments are:

* `github-pages` for documentation deployment from the default branch;
* `pypi` for package publishing with maintainer approval.

Environment protection rules are configured in GitHub and should be reviewed
with the external repository setup runbook.

## Local development

Local virtual environments, nox environments, build artifacts, and site output
are ignored and should not be committed.
