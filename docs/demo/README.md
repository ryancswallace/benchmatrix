# Basic demo

This demo runs inside the benchmatrix repository, where the normal pytest
configuration checks coverage for the complete package. `measure` isolates
those project-wide options so they do not distort the benchmark.

Collect the baseline:

```bash
uv run benchmatrix measure --runs 3 --output demo-baseline \
    docs/demo/basic_demo.py
```

Collect a deliberately slower candidate:

```bash
BENCHMATRIX_DEMO_SLOWDOWN=1 \
uv run benchmatrix measure --runs 3 --output demo-candidate \
    docs/demo/basic_demo.py
```

Compare them:

```bash
uv run benchmatrix compare demo-baseline demo-candidate \
    --threshold 5% \
    --fail-on-regression
```

Collection manifests preserve the managed pytest command. Start with new output
directories, or use `measure --resume` to continue an interrupted collection.
