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
* Spelling failure: run `make spellcheck` and fix the word or the dictionary.
* Type failure: run `make typecheck` and prefer code changes over ignores.
* Dependency audit failure: follow the dependency-update runbook.
* Docs failure: run `make docs-linkcheck` and fix the first strict-mode warning
    or broken generated-site link.
* Dockerfile lint failure: run `make docker-lint`, then inspect the reported
    Dockerfile.
* Workflow lint failure: run `make workflow-lint`, then inspect the reported
    workflow or `.github/labeler.yml`.
* Workflow environment failure: run `make workflow-env-lint`, then compare the
    referenced workflow environments with the GitHub repository settings.
* Dependabot update failure: confirm the update changed only the expected
    ecosystem files, then follow the dependency-update runbook.

## Do not do this

Do not skip a failing required check without documenting why the check is wrong
and how it will be repaired.
