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

Releases are prepared in a normal pull request and published by the GitHub
Actions release workflow after a GitHub Release is published.

1. Choose the next version from the changelog and compatibility policy.
2. Update release metadata:

   * set `project.version` in `pyproject.toml`;
   * set `version` in `CITATION.cff`;
   * add or update `date-released` in `CITATION.cff` once the release date is
     known.

3. Move user-visible `CHANGELOG.md` entries from `Unreleased` into a versioned
   section such as `## 0.2.0 - 2026-06-20`, then leave a fresh `Unreleased`
   section at the top.
4. Run the release validation commands:

   ```bash
   make check-all
   make build
   ```

5. Confirm `dist/` contains one source distribution, one wheel, and
   `benchmatrix.cdx.json` for the intended version.
6. Merge the release pull request after required checks pass.
7. Create and push an annotated tag named `vX.Y.Z` for the release commit.
8. Draft GitHub release notes from the changelog section for that version.
9. Publish the GitHub Release. Publishing the release triggers
   `.github/workflows/release.yml`, which rebuilds artifacts, attests them, and
   publishes to PyPI through Trusted Publishing.
10. Verify the package from PyPI in a clean environment.
11. If any post-release fix is needed, prepare a new patch release. Do not
    replace files for an already-published PyPI version.

The detailed operational checklist lives in `docs/runbooks/release.md`.
