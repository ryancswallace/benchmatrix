# Failed CI runbook

Use this when a pull request or default-branch CI run fails.

## Triage

1. Identify the failing job and first failing command.
2. Check whether the failure is deterministic by rerunning only if the error
   looks infrastructure-related.
3. Reproduce locally with the matching command:

   ```bash
   make check
   make test-matrix
   make docs
   ```

4. If the failure is Python-version-specific, run the matching nox session.

## Common fixes

* Ruff failure: run `make format`, then inspect the diff.
* Markdown failure: run `make markdownlint` and fix the reported file.
* Type failure: run `make typecheck` and prefer code changes over ignores.
* Dependency audit failure: follow the dependency-update runbook.
* Docs failure: run `make docs` and fix the first strict-mode warning.
* Labeler failure: run `make workflow-lint`, then inspect `.github/labeler.yml`.
* Dependabot update failure: confirm the update changed only the expected
  ecosystem files, then follow the dependency-update runbook.

## Do not do this

Do not skip a failing required check without documenting why the check is wrong
and how it will be repaired.
