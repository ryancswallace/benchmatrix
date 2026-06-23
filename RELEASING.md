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

See the detailed operational checklist in `docs/runbooks/release.md`.
