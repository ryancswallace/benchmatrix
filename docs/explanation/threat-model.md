# Threat model

benchmatrix is a development-time Python package. Its main risks are supply-chain
integrity, unsafe benchmark inputs, leaked credentials in repository files, and
misleading performance conclusions.

## In scope

* package source and release artifacts;
* dependency declarations and lockfiles;
* CI and local automation;
* benchmark metadata parsing from local JSON files.

## Out of scope

* accepting untrusted benchmark JSON as a remote service;
* production traffic measurement;
* sandboxing arbitrary benchmark target code.

## Controls

* Bandit checks source for common Python security issues.
* pip-audit checks locked dependencies for known vulnerabilities.
* detect-secrets checks repository content for accidental credentials.
* GitHub Actions use least-privilege read permissions by default.
* Release artifacts are built and smoke-tested before publishing.
