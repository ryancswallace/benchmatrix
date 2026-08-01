# Basic demo

<!-- markdownlint-disable MD033 MD034 -->
<video
  controls
  preload="metadata"
  poster="../assets/basic-demo.png"
  width="1200"
>
  <source
    src="https://github.com/ryancswallace/benchmatrix/releases/download/v1.0.0/basic-demo.mp4"
    type="video/mp4"
  >
  Your browser cannot play this video.
  <a href="https://github.com/ryancswallace/benchmatrix/releases/download/v1.0.0/basic-demo.mp4">
    Download the MP4 instead.
  </a>
</video>
<!-- markdownlint-enable MD033 MD034 -->

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
    --threshold 25% \
    --summary \
    --fail-on-regression
```

The intentionally slower `loop` implementation should make this command report
`Overall: FAIL` and exit with status `1`.

Collection manifests preserve the managed pytest command. Start with new output
directories, or use `measure --resume` to continue an interrupted collection.
