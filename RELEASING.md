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

## Release process

Releases are made by a maintainer:

1. Confirm `CHANGELOG.md` describes all user-visible changes.
2. Set the version in `pyproject.toml`.
3. Update the version and release date in `CITATION.cff`.
4. Run `make check`.
5. Build the distributions with `uv build`.
6. Validate them with `uv run twine check dist/*`.
7. Commit the release, create an annotated `vX.Y.Z` tag, and publish the tag.
8. Publish the source distribution and wheel to PyPI.
9. Add a new `Unreleased` section to `CHANGELOG.md`.

Release notes should summarize changes and link to the corresponding changelog
section. Publishing remains a manual maintainer action; CI/CD automation is
outside the current project scope.
