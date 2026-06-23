# External repository setup runbook

Use this when creating the repository, auditing repository settings, or preparing
for a release. These steps cover settings that are not fully configured by files
inside this repository.

## Before you start

1. Confirm you are an administrator for `ryancswallace/benchmatrix`.
2. Open the default branch and confirm the latest `make check` result is green.
3. Review `.github/settings.yml` and this runbook together. If they disagree,
    fix the repository file or the docs before changing external settings.

## Settings-as-code setup

1. Decide whether to use the GitHub Settings app for this repository.
2. If using it, install the app from `https://github.com/apps/settings` for only
    this repository.
3. Confirm `.github/settings.yml` is on `main`.
4. Watch the app output or repository settings after installation and verify:
    description, homepage, topics, merge strategies, vulnerability alerts,
    deployment environments, and `main` branch protection.
5. If the app reports an unsupported setting, configure that item manually and
    update `docs/explanation/repository-settings.md` with the exception.

## Branch protection or ruleset

1. Go to Settings -> Rules -> Rulesets or Settings -> Branches.
2. Create or verify protection for `main`.
3. Require pull requests before merging.
4. Require one approving review.
5. Require CODEOWNERS review.
6. Dismiss stale approvals on new commits.
7. Require approval of the most recent push by someone other than the pusher.
8. Require conversation resolution.
9. Require status checks and branch freshness.
10. Select these required checks:

     ```text
     Quality checks
     Package build and smoke test
     Minimum dependency tests
     Tests (ubuntu-24.04, Python 3.11)
     Tests (ubuntu-24.04, Python 3.12)
     Tests (ubuntu-24.04, Python 3.13)
     Tests (ubuntu-24.04, Python 3.14)
     ```

11. Require linear history.
12. Block force pushes.
13. Block branch deletion.
14. Save, then open a test pull request or inspect the branch protection summary
     to confirm the expected checks are enforced.

## Merge strategy settings

1. Go to Settings -> General -> Pull Requests.
2. Enable squash merging.
3. Enable rebase merging.
4. Disable merge commits.
5. Enable automatic branch deletion after merge.
6. Leave auto-merge disabled unless the project adopts a written auto-merge
    policy.

## Dependabot and security alerts

1. Go to Settings -> Advanced Security.
2. Enable dependency graph.
3. Enable Dependabot alerts.
4. Enable Dependabot security updates.
5. Confirm `.github/dependabot.yml` exists on `main` for version updates.
6. Enable secret scanning if available for the repository.
7. Enable push protection if available for the repository.
8. Enable private vulnerability reporting.
9. In your personal notification settings, watch repository security alerts or
    verify another maintainer is assigned to do so.

## Labels

1. Open Issues -> Labels in GitHub repository settings.
2. Compare the current repository labels with `.github/labels.yml`.
3. Create, rename, or update labels manually when the recommended label set
    changes.
4. Do not delete existing labels without checking whether open issues or pull
    requests still use them.

## GitHub Pages

GitHub Pages must be enabled once per repository before the documentation
workflow can deploy. This is intentionally a small click-ops step: the default
`GITHUB_TOKEN` can deploy to an existing Pages site, but it cannot enable Pages
for a repository that does not have a Pages site yet. If this step is skipped,
`actions/configure-pages` fails with `Get Pages site failed` and `Not Found`.

1. Confirm `make docs` passes locally and in CI.
2. Go to Settings -> Pages.
3. Set Build and deployment -> Source to GitHub Actions.
4. Verify the Settings app created the `github-pages` environment and
    restricted deployments to `main`.
5. Run the documentation workflow once from `main`.
6. Confirm the site resolves at `https://ryancswallace.github.io/benchmatrix/`.
7. If the site URL changes, update `mkdocs.yml`, `.github/settings.yml`,
    `pyproject.toml`, and docs that mention the URL.

## PyPI Trusted Publishing

1. Create or claim the PyPI project `benchmatrix`.
2. Verify the Settings app created the GitHub environment `pypi`, restricted
    deployments to `v*` tags, and configured required reviewer(s).
3. Do not add PyPI secrets to the environment when Trusted Publishing is the
    intended path.
4. In PyPI, open the project -> Publishing -> Add trusted publisher.
5. Configure:

    ```text
    owner: ryancswallace
    repository: benchmatrix
    workflow filename: release.yml
    environment: pypi
    ```

6. Confirm `.github/workflows/release.yml` grants `id-token: write` to the
    publish job and uses the `pypi` environment.
7. Do not add a long-lived PyPI token if Trusted Publishing works.
8. If a token is temporarily unavoidable, make it project-scoped, store it as
     an environment secret, and remove it after Trusted Publishing is working.

## Repository profile

1. Set the repository description to
    `Build pytest-benchmark matrices and parse benchmark results with lightweight Python utilities.`.
2. Set the homepage to `https://ryancswallace.github.io/benchmatrix/` once Pages
    is live.
3. Set topics:
    `benchmark`, `benchmarking`, `performance`, `pytest`, `pytest-benchmark`,
    `python`.
4. Keep issues enabled.
5. Disable wiki and projects unless maintainers intentionally adopt them.

## Review cadence

Run this checklist:

* before the first public release;
* after adding, renaming, or removing required CI jobs;
* after changing publishing or documentation deployment workflows;
* at least quarterly while the project is active.
