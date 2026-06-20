# Repository health

Repository health is the combination of clear ownership, passing automation,
current dependencies, and useful documentation.

## Expected signals

* `make check` passes locally and in CI.
* `make test-matrix` passes before compatibility-sensitive changes.
* Issues and pull requests have enough labels or descriptions to triage.
* Dependabot pull requests are reviewed regularly instead of accumulating.
* Security reports receive private acknowledgement before public disclosure.
* Documentation covers installation, usage, API reference, and maintainer tasks.

## Maintenance cadence

Review dependencies and CI health at least monthly, and before each release.
Refresh runbooks when a real incident exposes a missing step.
