# Release policy

benchmatrix uses [Semantic Versioning](https://semver.org/). The detailed
release checklist lives in [the release runbook](docs/runbooks/release.md), and
the publishing model is documented in [Publishing](docs/explanation/publishing.md).

## Compatibility summary

benchmatrix is currently pre-1.0:

* patch releases should preserve documented public behavior except for urgent
  security or correctness fixes;
* minor releases may include breaking public API changes;
* breaking changes, deprecations, Python support changes, and migration notes
  should be called out in the changelog and release notes.

Starting with 1.0, incompatible changes to the stable public API require a major
release. The stable public API is the set of names exported from
`benchmatrix.__init__` and documented in the generated API reference; private
modules and private names are not stable extension points.

For the full policy, see [Compatibility](docs/reference/compatibility.md),
[Lifecycle](docs/explanation/lifecycle.md), and
[Deprecations](docs/explanation/deprecations.md).

## Release operations

Use [docs/runbooks/release.md](docs/runbooks/release.md) when preparing and
publishing a release. The runbook covers version preparation, changelog updates,
release pull request automation, tag creation, draft GitHub Release review, PyPI
publication through Trusted Publishing, and post-publication verification.

Release notes come from [CHANGELOG.md](CHANGELOG.md). Keep user-visible changes
under `## Unreleased` until release preparation moves them into a dated version
section.
