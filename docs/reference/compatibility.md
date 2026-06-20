# Compatibility

This page defines the support surface for benchmatrix. It should agree with
`pyproject.toml`, CI, nox, release notes, and the security policy.

## Supported Python versions

benchmatrix supports CPython 3.11 through 3.14. The package metadata declares:

```toml
requires-python = ">=3.11,<3.15"
```

The local nox matrix runs tests on every supported Python version:

```bash
make test-matrix
```

Normal pull request CI verifies every supported Python version on Ubuntu and
runs a smoke compatibility check on macOS and Windows for the current default
Python version. The primary quality job uses the repository `.python-version`.
Run `make test-matrix` locally before changes that may affect Python-version
compatibility.

## Supported operating systems

The package is intended to be OS-independent Python code and is classified as
`Operating System :: OS Independent`.

Supported operating systems are:

* Linux;
* macOS;
* Windows.

Pull request CI runs the full supported-Python test matrix on Ubuntu and a
current-Python smoke test on macOS and Windows. Linux is the primary continuously
verified platform. macOS and Windows are supported by design because benchmatrix
does not rely on platform-specific APIs, but regressions that only appear on
those systems may require a maintainer or contributor with access to the
affected platform to confirm and validate the fix.

## Supported architectures

benchmatrix is pure Python and does not ship compiled extensions. No
architecture-specific behavior is part of the public contract.

Supported architectures are any architecture where a supported CPython version
and the runtime dependencies can be installed, including common `x86_64` and
`aarch64` environments. Architecture-specific issues in pytest, pytest-benchmark,
or optional development tools are handled according to impact and reproducibility.

## Public API stability

The stable public API is the set of names exported from `benchmatrix.__init__`
and documented in the generated API reference. Private modules and private names
are not stable extension points, including:

* modules whose names begin with `_`, such as `_schema.py`;
* functions, classes, constants, and attributes whose names begin with `_`;
* incidental implementation details not documented in user-facing docs.

Pre-1.0 releases may still make breaking public API changes in minor releases
when the change makes the package simpler, safer, or more correct. Breaking
changes must be documented in the changelog and release notes. Patch releases
should avoid breaking public API changes except for urgent security fixes or
cases where preserving the old behavior would be clearly harmful.

Starting with 1.0, incompatible public API changes require a major release.

## Supported release branches

The active support branch is `main`.

The project does not currently maintain long-lived release branches. Security and
compatibility fixes are normally released from `main` in the next patch or minor
release. Temporary release branches may be created for an active release or
security fix, but they are not a standing support channel unless announced in the
release notes.

## Security-fix policy

Security fixes are provided for the latest released version of benchmatrix. While
the project is pre-1.0, fixes are not routinely backported to older minor
versions.

A backport to an older release may be considered when all of the following are
true:

* the issue is high impact for installed users;
* a safe, minimal patch can be prepared without carrying substantial branch
  maintenance cost;
* the affected release still has meaningful user adoption;
* the maintainer has capacity to validate and publish the backport.

See `SECURITY.md` and the security-report runbook for reporting and disclosure
steps.

## Deprecation policy

Deprecations are used for documented public API or behavior when users need a
migration path. Private implementation details do not require deprecation.

Before 1.0, deprecated public API should normally remain available until at least
the next minor release unless removal is needed for security or correctness.
After 1.0, deprecated public API should normally remain available until the next
major release.

Each deprecation should include:

* the replacement or migration path;
* a changelog entry;
* removal timing when known;
* tests that preserve the deprecated behavior until removal.

## Runtime scope

benchmatrix is intended for synchronous Python callables. Async functions,
concurrent service load tests, and production latency monitoring are outside the
current scope.

## pytest-benchmark

pytest-benchmark remains the timing engine. benchmatrix relies on its fixture,
statistics, and JSON output format, then layers metadata and parsing conventions
on top.
