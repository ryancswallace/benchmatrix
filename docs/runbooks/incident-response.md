# Incident response runbook

Use this when the project may have shipped a bad release, leaked a secret, or
published misleading security or compatibility information.

## Stabilize

1. Stop the action that is making the incident worse.
2. Assign one maintainer as incident lead.
3. Create a private timeline with times, actions, and links.
4. Preserve logs, workflow runs, artifacts, and reports.

## Contain

* Bad package release: yank or deprecate the release if the registry supports it.
* Leaked secret: revoke or rotate the credential immediately.
* Broken docs: disable deployment or publish a correction.
* Broken CI automation: disable only the failing automation that creates risk.

## Fix

1. Create the smallest safe fix.
2. Add a regression test or validation check.
3. Run `make check` and any focused reproduction.
4. Prepare release notes or an advisory when users need action.

## Recover

1. Publish the fix.
2. Verify the fix from a clean environment.
3. Communicate impact and mitigation.
4. Update the relevant runbook with the missed step.
