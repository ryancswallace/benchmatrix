# Release policy

benchmatrix uses [Semantic Versioning](https://semver.org/).

## Compatibility

While the project is pre-1.0:

* patch releases contain compatible fixes and documentation improvements;
* minor releases may introduce breaking API changes;
* breaking changes should be called out clearly in the changelog.

Starting with 1.0, incompatible public API changes require a major release.
The supported public API is the set of names exported from
`benchmatrix.__init__`. Private modules and names beginning with an underscore
are not covered by the compatibility guarantee.

Python version support may change in a minor release before 1.0 and in a major
release after 1.0. Dropping a Python version will be documented in advance when
practical.

Release branches are not maintained as standing support branches. The active
support branch is `main`; temporary release or security branches may be used for
coordination and retired after release.

## Release process

Releases are prepared in a normal pull request, drafted automatically when a
`vX.Y.Z` tag is pushed, and published by the GitHub Actions release workflow
after the draft GitHub Release is reviewed and published.

1. Choose the next version from the changelog and compatibility policy.
2. Export the release version without a leading `v`:

    ```bash
    export BENCHMATRIX_RELEASE_VERSION=X.Y.Z
    ```

3. Update the `CHANGELOG.md` entries under `## Unreleased`.
4. Prepare the release metadata, validate locally, commit the release files,
    push the release branch, and open or reuse the standardized pull request:

    ```bash
    make release-pr-ready
    ```

    Add `RELEASE_DATE=YYYY-MM-DD` when the release date should be explicit. The
    target runs `make release-preflight`, `make prepare-release`, `make check`,
    and `make release-pr`. The preparation step updates `pyproject.toml`,
    `CITATION.cff`, and `CHANGELOG.md`, updates `date-released`, creates the
    dated changelog section, and runs `uv lock`. The pull request step creates
    `release/v$BENCHMATRIX_RELEASE_VERSION`, commits the release metadata files,
    pushes the branch, and opens or reuses the GitHub pull request.

5. Merge the release pull request after required checks pass.
6. Create and push the annotated release tag from the merged default branch:

    ```bash
    make release-tag
    ```

    This switches to `main`, pulls `origin/main` with `--ff-only`, validates the
    release metadata, refuses existing tags, and pushes
    `v$BENCHMATRIX_RELEASE_VERSION`.

7. Review the draft GitHub Release created by `.github/workflows/draft-release.yml`.
8. Publish the GitHub Release. Publishing the release triggers
    `.github/workflows/release.yml`, which rebuilds artifacts, attaches them to
    the GitHub Release, attests them, and publishes to PyPI through Trusted
    Publishing.
9. Verify the package from PyPI in a clean environment.
10. If any post-release fix is needed, prepare a new patch release. Do not
     replace files for an already-published PyPI version.

The detailed operational checklist lives in `docs/runbooks/release.md`.
