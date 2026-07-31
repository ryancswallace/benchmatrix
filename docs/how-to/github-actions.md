# Gate regressions in GitHub Actions

Run baseline and candidate measurements on the same runner. This avoids
mistaking differences between machines for differences between commits.

## Commit the comparison policy

Keep the gate in `pyproject.toml` so local and CI comparisons use the same
reviewed rules:

```toml
[tool.benchmatrix.compatibility]
mode = "permissive"

[tool.benchmatrix.evidence]
minimum_runs = 5
minimum_samples_per_run = 5

[tool.benchmatrix.regression]
default_threshold_percent = 5.0
```

Validate it without running benchmarks:

```bash
uv run benchmatrix policy validate --quiet
```

## Compare the pull request with its base commit

The following workflow checks out the pull request once, creates a detached
worktree for its base commit, and measures both revisions sequentially on one
runner. Replace `tests/test_benchmarks.py` with the project's benchmark target.

```yaml
name: Benchmarks

on:
  pull_request:

permissions:
  contents: read

jobs:
  compare:
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    env:
      BENCHMATRIX_VERSION: "1.1.0"

    steps:
      - name: Check out candidate
        uses: actions/checkout@v7
        with:
          fetch-depth: 0
          persist-credentials: false

      - name: Set up Python
        uses: actions/setup-python@v7
        with:
          python-version-file: .python-version

      - name: Set up uv
        uses: astral-sh/setup-uv@v9.0.0

      - name: Collect baseline
        shell: bash
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
        run: |
          base_dir="$RUNNER_TEMP/benchmark-base"
          git worktree add --detach "$base_dir" "$BASE_SHA"
          (
            cd "$base_dir"
            uv sync --locked
            uv pip install --python .venv/bin/python \
              "benchmatrix==$BENCHMATRIX_VERSION"
            uv run --no-sync benchmatrix measure \
              --runs 5 \
              --output "$RUNNER_TEMP/benchmark-baseline" \
              tests/test_benchmarks.py
          )

      - name: Collect candidate
        shell: bash
        run: |
          uv sync --locked
          uv pip install --python .venv/bin/python \
            "benchmatrix==$BENCHMATRIX_VERSION"
          uv run --no-sync benchmatrix measure \
            --runs 5 \
            --output "$RUNNER_TEMP/benchmark-candidate" \
            tests/test_benchmarks.py

      - name: Compare runs
        shell: bash
        run: |
          uv run --no-sync benchmatrix compare \
            "$RUNNER_TEMP/benchmark-baseline" \
            "$RUNNER_TEMP/benchmark-candidate" \
            --format json \
            --github-summary \
            --fail-on-regression \
            > "$RUNNER_TEMP/benchmark-comparison.json"

      - name: Upload benchmark evidence
        if: always()
        uses: actions/upload-artifact@v7
        with:
          name: benchmark-comparison
          path: |
            ${{ runner.temp }}/benchmark-baseline
            ${{ runner.temp }}/benchmark-candidate
            ${{ runner.temp }}/benchmark-comparison.json
          if-no-files-found: warn
          retention-days: 14
```

`--github-summary` appends the Markdown report to the job summary. The JSON
report and both collections remain available as workflow artifacts for later
inspection.

Pin `BENCHMATRIX_VERSION` to the release reviewed for your project. Installing
that same version after each revision's normal `uv sync` keeps the benchmark
tool constant while allowing project dependencies to follow each lockfile. The
benchmark target itself must exist on both revisions.

## Choose the runner deliberately

Shared GitHub-hosted runners are convenient but can be noisy. For a blocking
performance gate:

* keep baseline and candidate in the same job and run them close together;
* avoid unrelated CPU-heavy work in the benchmark job;
* collect several runs and keep evidence thresholds enabled;
* use a dedicated or otherwise stable runner when small changes matter;
* treat an inconclusive result as a reason to rerun or investigate, not as proof
    of a regression.

Do not execute code from untrusted forks on a persistent self-hosted runner
unless each job is strongly isolated and ephemeral. Keep this workflow on the
`pull_request` event—not `pull_request_target`—and retain minimal permissions.

The comparison report records environment compatibility, sample counts, IQR,
CV, outliers, and the resolved threshold for every matrix cell. Retain it when
debugging a failed gate.
