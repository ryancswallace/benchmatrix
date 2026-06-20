# Dependency update runbook

Use this for routine updates or vulnerability-driven dependency changes.

Dependabot opens routine update pull requests for the ecosystems configured in
`.github/dependabot.yml`. Treat those pull requests as the default path for
routine dependency maintenance unless a security fix or compatibility issue
needs a manual update sooner.

## Steps

1. Identify whether the dependency is runtime, development, Node, or GitHub
   Actions tooling. For Dependabot pull requests, confirm that the ecosystem,
   labels, and changed files match the update described in the pull request.
2. Update the declaration in the appropriate file.
3. Refresh locks:

   ```bash
   uv lock
   npm install
   ```

   Use only the command that matches the changed ecosystem.

4. Run focused checks:

   ```bash
   make deps
   make audit
   npm audit --audit-level=moderate
   ```

5. Run full validation:

   ```bash
   make check
   ```

6. If the update can affect supported Python behavior, run:

   ```bash
   make test-matrix
   ```

7. Add a changelog entry when users or maintainers should know.

For Dependabot pull requests, steps 2 and 3 are usually already done by the bot.
Do not merge until CI passes and the diff is limited to the expected manifests,
lockfiles, workflow files, or devcontainer files.

## Dependabot-specific handling

1. Check the pull request title and labels. Expected labels are `dependencies`
   and `maintenance`, with ecosystem-specific labels when useful.
2. Review release notes for major updates, security updates, build backends,
   pytest, pytest-benchmark, Ruff, basedpyright, uv, and GitHub Actions.
3. Let CI complete. If CI fails, reproduce locally with the command reported by
   the failed job.
4. For Python updates that touch supported-version behavior, run:

   ```bash
   make test-matrix
   ```

5. Merge only after a human review. Auto-merge is intentionally not part of the
   baseline policy.

## Manual Dependabot maintenance

If Dependabot becomes noisy, lower the relevant `open-pull-requests-limit`, add
or adjust groups, or temporarily set that ecosystem's limit to `0`. If
Dependabot misses an ecosystem, confirm the manifest location and package
ecosystem value in `.github/dependabot.yml`.

## If an update fails

Pin or revert the problematic update, record the reason in the pull request, and
open a follow-up issue if the update is security-relevant.
