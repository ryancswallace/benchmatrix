# Security policy

## Supported versions

Security fixes are provided for the latest released version of benchmatrix.
Because the project is currently pre-1.0, fixes are not routinely backported to
older minor versions.

The active support branch is `main`. Temporary security release branches may be
created for coordinated disclosure, but they are not maintained after the fix is
released unless the release notes explicitly say otherwise.

A backport to an older release may be considered when the issue is high impact,
the patch is small and safe, the affected release still has meaningful user
adoption, and the maintainer has capacity to validate and publish the backport.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability.

Email Ryan Wallace at <ryancswallace@gmail.com> with:

* the affected version;
* steps to reproduce the issue;
* the potential impact;
* any suggested mitigation, if known.

You should receive an acknowledgement within seven days. The maintainer will
coordinate validation, remediation, and disclosure with the reporter. Please
allow a reasonable period for a fix before publishing details.
