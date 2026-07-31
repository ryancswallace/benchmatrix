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

Security fixes are provided for the latest minor line in the current major
series. Users must run the latest patch in that line to receive fixes. Older
minor lines and previous major series do not receive routine backports or
long-term support.

Security and compatibility fixes are normally prepared on `main` and released
from there. A narrowly scoped backport may be made when impact and adoption
justify it, but it is not part of the support guarantee.

For the full support and backport policy, see
[Compatibility](docs/reference/compatibility.md#security-fix-policy) and
[Lifecycle](docs/explanation/lifecycle.md).

## Related documentation

* [Threat model](docs/explanation/threat-model.md)
* [Secrets handling](docs/explanation/secrets.md)
* [Security report runbook](docs/runbooks/security-report.md)
* [Incident response runbook](docs/runbooks/incident-response.md)
