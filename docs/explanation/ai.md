# AI-agent guidance

AI-agent instructions should stay concise and operational. They should tell an
agent what commands are authoritative, what APIs must remain stable, and where to
avoid broad changes.

## Expectations

* Prefer updating existing files over duplicating content.
* Keep docs, CI, Make targets, nox sessions, and pyproject configuration aligned.
* Run `make check` after edits.
* Preserve user work in a dirty tree.
* Avoid broad type, lint, or security suppressions.

## Documentation updates

When an agent changes behavior, it should update the relevant tutorial, how-to,
reference page, or runbook in the same change.
