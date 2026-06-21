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

3. Update version metadata:

   * `pyproject.toml`: set `[project] version = "X.Y.Z"`;
   * `CITATION.cff`: set `version: X.Y.Z`;
   * `CITATION.cff`: add or update `date-released: "YYYY-MM-DD"` when the
     release date is known.

4. Update `CHANGELOG.md`:

   * keep `## Unreleased` at the top;
   * create `## X.Y.Z - YYYY-MM-DD` below it;
   * move user-visible entries from `Unreleased` into the versioned section;
   * call out breaking changes, Python support changes, deprecations, and
     security fixes explicitly.

5. Run local validation:

   ```bash
   make check
   make test-matrix
   ```

6. Build and smoke-test the artifacts locally:

   ```bash
   make build
   ```

7. Inspect `dist/`:

   ```bash
   ls -1 dist
   ```

   Confirm the directory contains exactly these release artifacts for `X.Y.Z`:

   * `benchmatrix-X.Y.Z.tar.gz`;
   * `benchmatrix-X.Y.Z-py3-none-any.whl`;
   * `benchmatrix.cdx.json`.

8. Open a pull request, wait for required checks, and merge it normally.

## Tag and publish

1. After merging, update the local default branch.
2. Create an annotated tag for the release commit:

   ```bash
   git tag -a vX.Y.Z -m "benchmatrix X.Y.Z"
   git push origin vX.Y.Z
   ```

3. On GitHub, create a new release for tag `vX.Y.Z`.
4. Use release notes copied from the `CHANGELOG.md` section for `X.Y.Z`.
5. Publish the GitHub Release.
6. Watch `.github/workflows/release.yml`.

The release workflow runs on the GitHub `release` event with the `published`
activity type. Drafting a release does not publish to PyPI; publishing the
GitHub Release does. The publish job only runs when the workflow ref starts with
`refs/tags/v`, so releases must use tags such as `v0.2.0`. The workflow rebuilds
distributions from the tagged source, generates the SBOM, smoke-tests the wheel,
creates artifact attestations, and then publishes to PyPI from the `pypi`
environment.

If the `pypi` environment requires approval, approve the deployment only after
confirming the tag, changelog, and workflow run are for the intended version.

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
4. Check the release workflow artifacts and attestations.
5. Confirm the Release verification workflow installed `benchmatrix==X.Y.Z`
   from PyPI and imported `BenchmarkCase` successfully.
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
* `pyproject.toml`, `CITATION.cff`, and the Git tag disagree;
* built artifact filenames do not contain the intended version;
* the GitHub Release points at the wrong tag or a tag that does not start with
  `v`;
* the PyPI Trusted Publisher or `pypi` environment is missing or misconfigured.

If publication already happened, do not delete or overwrite the PyPI release.
Prepare a follow-up patch release, and yank the bad file only when users should
stop installing it.
