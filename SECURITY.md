# Security policy

Please do not open a public issue for a suspected vulnerability.

## Reporting a vulnerability

Email Ryan Wallace at <ryancswallace@gmail.com> with:

* the affected version;
* steps to reproduce the issue;
* the potential impact;
* any suggested mitigation, if known.

You should receive an acknowledgement within seven days. The maintainer will
coordinate validation, remediation, and disclosure with the reporter. Please
allow a reasonable period for a fix before publishing details.

## Support scope

Security fixes are provided for the latest released version of benchmatrix.
Because the project is currently pre-1.0, older minor versions are not routinely
backported. Security and compatibility fixes are normally prepared on `main` and
released from there.

For the full support and backport policy, see
[Compatibility](docs/reference/compatibility.md#security-fix-policy) and
[Lifecycle](docs/explanation/lifecycle.md).

## Related documentation

* [Threat model](docs/explanation/threat-model.md)
* [Secrets handling](docs/explanation/secrets.md)
* [Security report runbook](docs/runbooks/security-report.md)
* [Incident response runbook](docs/runbooks/incident-response.md)
