# Release runbook

Use this when preparing and publishing a benchmatrix release.

## Preconditions

* You have maintainer permission for `ryancswallace/benchmatrix`.
* The default branch is green.
* The GitHub `pypi` environment exists and has the intended reviewers.
* PyPI Trusted Publishing is configured for `release.yml` and the `pypi`
  environment.
* You know the exact version being released, such as `0.2.0`.

Before the first public release, complete the external repository setup runbook,
especially the `pypi` environment and PyPI Trusted Publishing checklist.

## Prepare the release pull request

1. Start from an up-to-date `main` branch.
2. Choose the release version:

    * patch for compatible fixes and documentation;
    * minor for new features or pre-1.0 breaking changes;
    * major for post-1.0 breaking public API changes.

3. Update the `CHANGELOG.md` entries under `## Unreleased`. Call out breaking
    changes, Python support changes, deprecations, and security fixes explicitly.
4. Prepare release metadata:

    ```bash
    make prepare-release RELEASE_VERSION=X.Y.Z
    ```

    This command updates `pyproject.toml`, `CITATION.cff`, and `CHANGELOG.md`,
    sets `date-released` in `CITATION.cff`, creates the dated changelog section,
    and runs `uv lock` after the `pyproject.toml` version changes.

    To use an explicit release date instead of today's date, run:

    ```bash
    make prepare-release RELEASE_VERSION=X.Y.Z RELEASE_DATE=YYYY-MM-DD
    ```

5. Run local validation:

    ```bash
    make check
    ```

    `make check` builds and smoke-tests the distribution artifacts as part of the
    validation suite.

6. Inspect `dist/`:

    ```bash
    ls -1 dist
    ```

    Confirm the directory contains these release artifacts for `X.Y.Z`:

    * `benchmatrix-X.Y.Z-py3-none-any.whl`;
    * `benchmatrix-X.Y.Z.tar.gz`;
    * `benchmatrix.cdx.json`.

7. Open a pull request, wait for required checks, and merge it normally.

## Tag and publish

1. After merging, update the local default branch.
2. Create and push an annotated tag for the release commit:

    ```bash
    git tag -a vX.Y.Z -m "benchmatrix X.Y.Z"
    git push origin vX.Y.Z
    ```

3. Wait for `.github/workflows/draft-release.yml` to create or update the draft
    GitHub Release for `vX.Y.Z`. The workflow validates that the tag version,
    package metadata, citation metadata, and changelog section agree before it
    drafts the release notes from `CHANGELOG.md`.
4. Open the draft GitHub Release. Confirm the tag, title, and notes are correct.
5. Publish the draft GitHub Release.
6. Watch `.github/workflows/release.yml` through the publish and verification
    jobs.

The draft-release workflow intentionally stops at a draft. The workflow uses
`GITHUB_TOKEN`, and GitHub suppresses most follow-on workflow runs caused by that
token to avoid recursive automation. Publishing the draft from GitHub remains the
deliberate deployment action that triggers PyPI publication.

The release workflow runs on the GitHub `release` event with the `published`
activity type. Drafting a release does not publish to PyPI; publishing the
GitHub Release does. The publish job only runs when the workflow ref starts with
`refs/tags/v`, so releases must use tags such as `v0.2.0`. The workflow rebuilds
distributions from the tagged source, generates the SBOM, smoke-tests the wheel,
creates artifact attestations, uploads package distributions and the SBOM as
separate workflow artifacts, attaches those files to the GitHub Release, and
then publishes only the distributions to PyPI from the `pypi` environment.

If the `pypi` environment requires approval, approve the deployment only after
confirming the tag, changelog, and workflow run are for the intended version.
The verification job depends on the publish job, so it verifies the package
after publication rather than racing the publishing job.

## Verify after publication

1. Open `https://pypi.org/project/benchmatrix/X.Y.Z/` and confirm:

    * the version is visible;
    * the source distribution and wheel are present;
    * project metadata, license, Python requirements, and links look correct.

2. Install from PyPI in a clean environment:

    ```bash
    verify_env=$(mktemp -d)
    uv venv --quiet "$verify_env"
    VIRTUAL_ENV="$verify_env" uv pip install --quiet "benchmatrix==X.Y.Z"
    "$verify_env/bin/python" -c "from benchmatrix import BenchmarkCase; print(BenchmarkCase.__name__)"
    rm -rf "$verify_env"
    ```

3. Confirm the command prints `BenchmarkCase`.
4. Check the GitHub Release assets, release workflow artifacts, and
    attestations. Confirm the Release page lists the source distribution, wheel,
    and SBOM in addition to GitHub's automatic source archives.
5. Confirm the release workflow's `Verify PyPI install` job installed
    `benchmatrix==X.Y.Z` from PyPI and imported `BenchmarkCase` successfully.
6. Confirm the Docker workflow published and smoke-tested the GHCR images for
    the release tag.
7. Confirm the documentation deployment for `main` completed if release docs
    changed.
8. Close the release issue or checklist item, if one exists.

## Manual workflow dispatch

`.github/workflows/release.yml` also supports manual dispatch. Use it with
`publish` set to `false` for a build-only release smoke check. Use
`publish=true` only for an intentional publication from a tag ref named
`refs/tags/vX.Y.Z`; the publish job is guarded and will not run from branch refs
or non-`v` tags.

## Abort conditions

Abort before publishing if any of these are true:

* validation fails;
* the changelog is missing user-visible changes;
* `pyproject.toml`, `CITATION.cff`, `CHANGELOG.md`, and the Git tag disagree;
* built artifact filenames do not contain the intended version;
* the GitHub Release points at the wrong tag or a tag that does not start with
  `v`;
* the PyPI Trusted Publisher or `pypi` environment is missing or misconfigured.

If publication already happened, do not delete or overwrite the PyPI release.
Prepare a follow-up patch release, and yank the bad file only when users should
stop installing it.
