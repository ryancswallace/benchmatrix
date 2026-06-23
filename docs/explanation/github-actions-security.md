# GitHub Actions security

CI should verify project health without granting unnecessary write access.

## Baseline posture

* Default workflow permissions are read-only.
* Checkout does not persist credentials unless a job needs to push.
* The pull request labeler uses `pull_request_target` without checkout and only
    receives the permission needed to add existing pull request labels.
* Workflow actions use carefully versioned refs and Dependabot updates. The
    `.github/zizmor.yml` policy records this choice and disables only zizmor's
    SHA-pinning audit until the project adopts full action SHA pinning.
* Scheduled audits are separated from normal pull request validation.
* Documentation deployment uses the `github-pages` environment with `pages:
    write` and OIDC only in the deployment job.
* Package publishing uses the `pypi` environment and PyPI Trusted Publishing
    instead of long-lived publishing tokens.
* Release artifacts are attested with GitHub artifact attestations before they
    are published.
* Docker images are built in a dedicated workflow, scanned with Trivy, and only
    pushed from non-pull-request events with `packages: write`.
* Artifacts should be limited to build outputs such as distributions, container
    images, SBOM files, and attestation metadata.

## Pull requests

Avoid workflows that run untrusted pull request code with repository write
tokens. If a workflow needs elevated permissions, isolate it from arbitrary code
execution and document why the permission is needed.

## Maintenance

Run actionlint and zizmor locally with:

```bash
make workflow-lint
```

Keep action versions current as part of dependency maintenance.
