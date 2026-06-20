# Repository settings

This page is the recommended external setup baseline for `ryancswallace/benchmatrix`.
Prefer settings-as-code where available, then complete the checklist items that
GitHub, PyPI, or another external service still require in their own UI.

## Settings-as-code

The repository includes `.github/settings.yml` for the GitHub Settings app. If
the app is installed, changes merged to the default branch sync these settings:

* repository description, homepage, topics, issues/projects/wiki flags, and
  branch deletion after merge;
* allowed merge strategies: squash and rebase enabled, merge commits disabled;
* Dependabot alerts and automated security fixes;
* `main` branch protection, including required reviews, code owner review,
  stale review dismissal, last-push approval, required status checks, linear
  history, blocked force pushes, blocked deletions, and conversation resolution.

Install the Settings app only after branch protection is active enough that
changes to `.github/settings.yml` require review. The app can change repository
administration settings from a merged pull request, so treat this file as
security-sensitive configuration.

## Main branch protection or ruleset

Use either a GitHub ruleset or branch protection for `main`. Rulesets are
preferred when available because they are visible to readers and can layer with
other rules. If using the Settings app, `.github/settings.yml` configures a
classic branch protection rule; if using rulesets instead, mirror these settings
manually:

* require a pull request before merging;
* require at least one approving review;
* require CODEOWNERS review;
* dismiss stale approvals when new commits are pushed;
* require approval of the most recent push by someone other than the pusher;
* require all review conversations to be resolved;
* require the branch to be up to date before merge;
* block force pushes;
* block branch deletion;
* require linear history.

Required PR status checks:

* `Quality checks`;
* `Package build and smoke test`;
* `Minimum dependency tests`;
* `Tests (ubuntu-24.04, Python 3.11)`;
* `Tests (ubuntu-24.04, Python 3.12)`;
* `Tests (ubuntu-24.04, Python 3.13)`;
* `Tests (ubuntu-24.04, Python 3.14)`.

Do not require scheduled-only jobs, manual label-sync jobs, or deployment jobs
for every pull request unless they become fast, deterministic PR checks.

## Merge and pull request policy

Recommended merge settings:

* enable squash merge;
* enable rebase merge;
* disable merge commits;
* delete head branches automatically after merge;
* keep auto-merge disabled until the project has a clear policy for bot PRs.

Require contributors to use pull requests for all default-branch changes. For
trivial maintainer-only metadata updates, a pull request can still be short; the
review trail matters more than ceremony.

## Security and analysis

Enable these in GitHub repository settings:

* Dependabot alerts;
* Dependabot security updates;
* dependency graph;
* secret scanning;
* push protection;
* private vulnerability reporting.

The repository also has local safety nets: `pip-audit`, `detect-secrets`,
Bandit, lockfile checks, and scheduled dependency audit CI. Those do not replace
GitHub-side alerting and push protection because GitHub can catch events before
or outside normal local validation.

## GitHub Pages

The documentation site is configured for:

* URL: `https://ryancswallace.github.io/benchmatrix/`;
* source content: `docs/` plus generated API reference pages;
* local validation: `make docs`.

If publishing the site, set Pages to deploy with GitHub Actions rather than a
branch source. Use the `github-pages` environment and restrict deployment to the
default branch. Do not commit the generated `site/` directory.

## GitHub environments

Create environments before wiring publish workflows to them:

* `github-pages` for documentation deployment;
* `pypi` for package publishing.

For `pypi`, require trusted maintainer review before deployment and restrict
deployments to release refs when the repository plan supports it. Keep secrets
out of the environment when using PyPI Trusted Publishing because OIDC should
provide a short-lived publishing token.

## PyPI Trusted Publishing

When the PyPI project exists, configure a Trusted Publisher in PyPI for GitHub
Actions:

* PyPI project: `benchmatrix`;
* owner: `ryancswallace`;
* repository: `benchmatrix`;
* workflow filename: `release.yml`;
* environment: `pypi`.

The release workflow publishes when a GitHub Release is published from a tag
whose ref starts with `refs/tags/v`. Confirm the `publish` job has job-level
`id-token: write`, uses the `pypi` environment, and runs
`pypa/gh-action-pypi-publish@release/v1` without a stored password.

Do not create a long-lived PyPI API token unless Trusted Publishing is blocked.
If a token is temporarily required, scope it to the `benchmatrix` project and
store it only as an environment secret.

## Repository profile

Set these repository profile fields:

* description: `pytest-benchmark matrix utilities and result parsing.`;
* homepage: `https://ryancswallace.github.io/benchmatrix/` once Pages is live;
* topics: `benchmark`, `benchmarking`, `performance`, `pytest`,
  `pytest-benchmark`, `python`.

Disable the wiki and projects unless the project starts using them deliberately.
Keep issues enabled.

## Manual verification cadence

Review these settings after major workflow changes, before the first public
release, and at least quarterly. The external setup runbook has the operational
checklist.
