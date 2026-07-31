# Lifecycle

benchmatrix 1.x is stable software governed by Semantic Versioning. Documented
public behavior remains backward compatible throughout a major release series
unless an urgent security or correctness issue makes that unsafe.

## Support lifecycle

`main` is the active development and support branch. The project does not keep
standing long-lived release branches. Routine fixes, compatibility updates, and
security fixes are prepared on `main` and released from there.

Temporary release branches may be used for an active release candidate,
coordinated security fix, or urgent patch. Unless release notes say otherwise,
those branches are retired after the release is complete.

## Version support

The latest minor line in the current major series is supported. Users must run
the latest patch in that line to receive routine correctness, compatibility, and
security fixes. For example, after `1.2.1` is released, the supported 1.x line is
`1.2`, and users should upgrade to `1.2.1`.

Older minor lines and previous major series do not receive routine backports.
The project does not maintain standing long-term-support releases. A narrowly
scoped backport may be made when impact and adoption justify it, but it is not
part of the support guarantee.

## Change stages

* **Experimental**: behavior may change without deprecation. This includes
    undocumented internals, private modules, and private names.
* **Documented**: behavior appears in docs or examples and should receive a
    changelog note when changed.
* **Stable public API**: exported from `benchmatrix.__init__`, documented in the
    API reference, and covered by tests.
* **Deprecated**: retained temporarily with migration guidance.
* **Removed**: no longer available after the documented removal release or after
    an urgent security/correctness removal.

## Public API stability

Patch releases preserve documented public behavior except for urgent security
or correctness fixes. Minor releases add backward-compatible behavior and may
introduce deprecations. Incompatible changes to the stable public API require a
major release. Private implementation details remain outside the compatibility
contract.

## Release signal

Use the changelog to communicate user-visible changes. Use release notes to call
out compatibility risk, supported Python changes, deprecations, removals, and
required migration steps.
