# First release

Before the first public release, confirm the project has enough operational
structure to support users after publication.

## Checklist

* package metadata has real maintainers, license, URLs, and classifiers;
* README explains the core use case;
* API docs build from docstrings;
* `make check` passes;
* `make test-matrix` passes;
* `make build` produces a source distribution, wheel, and SBOM;
* the built wheel can be installed and imported in a clean environment;
* changelog has a dated version section;
* `pyproject.toml`, `CITATION.cff`, the Git tag, and release notes use the same
    version;
* security and support policies are present;
* the GitHub `pypi` environment exists with trusted maintainer reviewers;
* PyPI Trusted Publishing is configured for `release.yml` and the `pypi`
    environment;
* a maintainer knows how to verify the package after PyPI publication.

If any item is missing, fix it before uploading artifacts. A delayed first
release is easier to recover from than a broken first release.
