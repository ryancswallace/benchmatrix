# Ownership transfer runbook

Use this when maintainership, repository ownership, or package publishing control
changes.

## Before transfer

1. Identify the new maintainer or owning organization.
2. Confirm they have accepted the code of conduct, license, and release policy.
3. Inventory access: GitHub repository, package registry, documentation hosting,
   security advisories, and any automation secrets.
4. Remove credentials that should not transfer personally.

## Transfer

1. Add the new maintainer with the least privilege needed.
2. Transfer package registry ownership or add a verified publisher.
3. Update repository metadata, maintainers, citation metadata, and docs.
4. Run `make check` after metadata changes.
5. Announce the change in the changelog or release notes when users should know.

## After transfer

1. Confirm the new maintainer can run CI and publish a test release if needed.
2. Remove old maintainers who no longer need access.
3. Rotate any shared credentials.
4. Review branch protection and required checks.
