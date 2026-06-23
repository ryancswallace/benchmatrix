# Publishing

Publishing should be boring: build from a clean tree, verify artifacts, publish
once, then verify the public package.

## Package artifacts

Use:

```bash
make build
```

This command builds the source distribution and wheel, checks metadata with
Twine, installs the built wheel into a temporary environment, imports the public
package, generates the runtime CycloneDX SBOM at `dist/benchmatrix.cdx.json`,
and fails unless the release artifact files in `dist/` are the expected
wheel, source distribution, and SBOM for the package version in `pyproject.toml`.

The release workflow runs the same command before publishing, so local release
checks and CI release checks exercise the same path.

## Version metadata

The project uses static package metadata, but release preparation is automated.
After the `CHANGELOG.md` entries under `## Unreleased` are ready, export the
release version without a leading `v`, then run the release pull request
preparation target:

```bash
export BENCHMATRIX_RELEASE_VERSION=X.Y.Z
make release-pr-ready
```

This command checks release prerequisites, updates `pyproject.toml`,
`CITATION.cff`, and `CHANGELOG.md`, sets `date-released` in `CITATION.cff`,
creates the dated changelog section, runs `uv lock` after the `pyproject.toml`
version changes, runs the full local `make check` suite, and creates or reuses
the standardized release branch, commit, and GitHub pull request. Use
`RELEASE_DATE=YYYY-MM-DD` when the release date should be explicit.

After the release pull request is merged, create the Git tag with:

```bash
make release-tag
```

The tag must be named `vX.Y.Z` and must match the package version `X.Y.Z`.
Do not publish if the tag and metadata disagree.

## Changelog and release notes

`CHANGELOG.md` is the source of truth for release notes. During release
preparation, move entries from `Unreleased` into a dated version section. Keep
release notes practical: describe what changed, who is affected, and whether any
migration is required.

GitHub Release notes should summarize the same versioned changelog section. They
should mention breaking changes, deprecations, security fixes, and support-policy
changes before routine maintenance items.

## GitHub Release publishing flow

Pushing an annotated tag named `vX.Y.Z` starts `.github/workflows/draft-release.yml`.
That workflow validates release metadata, extracts notes from `CHANGELOG.md`,
and creates or updates a draft GitHub Release for the pushed tag.

`.github/workflows/release.yml` publishes when a GitHub Release is published.
The workflow listens for:

```yaml
release:
  types:
    - published
```

That means creating or editing a draft release is safe. Publishing the release is
the deployment action. The draft-release workflow uses `GITHUB_TOKEN`, so it
intentionally stops before publication; GitHub suppresses most follow-on
workflow runs caused by that token to avoid recursive automation.

The publish job is guarded with `startsWith(github.ref, 'refs/tags/v')`, so PyPI
publication only runs from version tags such as `v0.2.0`. The workflow builds
from the tagged source, uploads package distributions and the SBOM as separate
Actions artifacts, attaches those files to the GitHub Release, attests them, and
publishes only the distributions to PyPI from the `pypi` environment.

The workflow also has manual dispatch. Treat `publish=false` as a build smoke
check. Treat `publish=true` as a real publication and only run it from an exact
`refs/tags/vX.Y.Z` release ref.

## PyPI Trusted Publishing

Publishing uses PyPI Trusted Publishing rather than a long-lived API token. The
release job grants `id-token: write` only to the publishing job so the PyPI
publish action can exchange GitHub's OIDC identity for a short-lived PyPI token.
No PyPI username, password, or token should be stored in the repository.

Configure the PyPI trusted publisher with:

* owner: `ryancswallace`;
* repository: `benchmatrix`;
* workflow filename: `release.yml`;
* environment: `pypi`.

The workflow uses `pypa/gh-action-pypi-publish@release/v1`, which is the stable
publishing interface for Trusted Publishing.

## GitHub `pypi` environment

The `pypi` environment is the human approval gate for package publication. In
GitHub repository settings:

1. Create an environment named `pypi`.
2. Add trusted maintainer reviewers.
3. Restrict deployment branches or tags to release refs if the repository plan
   supports that control.
4. Do not add PyPI secrets when Trusted Publishing works.
5. If a temporary token is unavoidable, use a project-scoped token, store it only
   in the `pypi` environment, and remove it after Trusted Publishing succeeds.

## Documentation artifacts

Use:

```bash
make docs
```

Documentation should be built from the same revision as the release. API pages
are generated from package docstrings during the MkDocs build. The docs workflow
deploys the site from `main`; it does not publish package artifacts.

## Post-publication verification

After PyPI publication, verify from a clean environment:

```bash
verify_env=$(mktemp -d)
uv venv --quiet "$verify_env"
VIRTUAL_ENV="$verify_env" uv pip install --quiet "benchmatrix==X.Y.Z"
"$verify_env/bin/python" -c "from benchmatrix import BenchmarkCase; print(BenchmarkCase.__name__)"
rm -rf "$verify_env"
```

The command should print `BenchmarkCase`. The release workflow's verification
job runs that same post-publication smoke check after a GitHub Release is
published. Also
inspect the PyPI project page, release workflow logs, GitHub Release assets,
Actions artifacts, SBOM, and attestations.
