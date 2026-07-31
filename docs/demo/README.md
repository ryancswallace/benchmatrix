# Basic demo

This demo runs inside the benchmatrix repository, where pytest normally checks
coverage for the complete package. Pass `--no-cov` to the nested pytest command
so the demo is evaluated as a benchmark instead of as the project's full test
suite.

Collect the baseline:

```bash
uv run benchmatrix collect --runs 3 --output demo-baseline -- \
    uv run pytest -q --no-cov docs/demo/basic_demo.py
```

Collect a deliberately slower candidate:

```bash
BENCHMATRIX_DEMO_SLOWDOWN=1 \
uv run benchmatrix collect --runs 3 --output demo-candidate -- \
    uv run pytest -q --no-cov docs/demo/basic_demo.py
```

Compare them:

```bash
uv run benchmatrix compare demo-baseline demo-candidate \
    --threshold 5% \
    --fail-on-regression
```

Collection manifests preserve the pytest command. If a collection was created
without `--no-cov`, start again with a new output directory or move the failed
directory aside before using these commands.
