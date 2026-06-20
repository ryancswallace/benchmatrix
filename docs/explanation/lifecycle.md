# Lifecycle

benchmatrix is pre-1.0 software. Compatibility matters, but the project may still
make breaking changes when the API needs to become simpler, safer, or more
correct.

## Support lifecycle

`main` is the active development and support branch. The project does not keep
standing long-lived release branches. Routine fixes, compatibility updates, and
security fixes are prepared on `main` and released from there.

Temporary release branches may be used for an active release candidate,
coordinated security fix, or urgent patch. Unless release notes say otherwise,
those branches are retired after the release is complete.

## Version support

The latest released version is the supported version. While benchmatrix is
pre-1.0, older minor versions do not routinely receive backports. Users should
expect to upgrade to the latest patch or minor release for fixes.

After 1.0, the project may adopt a broader branch-support policy if usage
justifies it. Until then, the compatibility page and `SECURITY.md` are the source
of truth.

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

Before 1.0, minor releases may include breaking public API changes. Patch
releases should preserve documented public behavior unless a security or
correctness issue makes that unsafe.

Starting with 1.0, incompatible changes to the stable public API require a major
release. Private implementation details remain outside the compatibility
contract.

## Release signal

Use the changelog to communicate user-visible changes. Use release notes to call
out compatibility risk, supported Python changes, deprecations, removals, and
required migration steps.
