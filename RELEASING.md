# Release policy

benchmatrix uses [Semantic Versioning](https://semver.org/). The detailed
release checklist lives in [the release runbook](docs/runbooks/release.md), and
the publishing model is documented in [Publishing](docs/explanation/publishing.md).

## Compatibility summary

benchmatrix 1.x follows Semantic Versioning:

* patch releases preserve documented public behavior except for urgent
    security or correctness fixes;
* minor releases add backward-compatible behavior and may include
    deprecations;
* major releases may include incompatible public API changes;
* breaking changes, deprecations, Python support changes, and migration notes
    are called out in the changelog and release notes.

Incompatible changes to the stable Python API, CLI, configuration schema,
built-in decision defaults, or supported serialized-document readers require a
major release. The stable Python API is the set of names exported from
`benchmatrix.__init__` and documented in the generated API reference; private
modules and private names are not stable extension points. A new serialized
document version may ship in a minor release when all earlier 1.x document
versions remain readable.

The latest minor line in the current major series is supported, and users must
run its latest patch to receive routine correctness and security fixes. The
project does not maintain standing long-term-support branches.

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
