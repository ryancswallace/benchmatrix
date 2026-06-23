# Security report runbook

Use this when a vulnerability is reported privately.

## First hour

1. Acknowledge receipt privately.
2. Do not discuss details in public issues or pull requests.
3. Preserve the original report and reporter contact.
4. Triage affected versions, exploitability, and whether the issue is runtime or
    development-only.

## Investigation

1. Reproduce the issue in a private branch or fork.
2. Identify the smallest safe fix.
3. Add a regression test when possible.
4. Run:

    ```bash
    make check
    make test-matrix
    ```

## Remediation

1. Prepare a private advisory if supported by the host.
2. Coordinate disclosure timing with the reporter.
3. Release patched versions.
4. Publish the advisory with affected versions and mitigation guidance.
5. Credit the reporter if they want credit.

## If credentials are involved

Immediately rotate or revoke the credential, then follow the incident-response
runbook.
