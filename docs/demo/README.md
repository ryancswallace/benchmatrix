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

## Record and publish the demo

Install [VHS](https://github.com/charmbracelet/vhs), then regenerate the video
and its poster from the repository root:

```bash
vhs docs/demo/basic_demo.tape
```

The tape writes the video to `docs/assets/basic-demo.mp4` and the final frame to
`docs/assets/basic-demo.png`. The MP4 is ignored by Git because it is published
as a GitHub release asset instead.

After the target release exists, authenticate the GitHub CLI and upload the
video by specifying its tag:

```bash
gh auth login
make demo-upload DEMO_RELEASE_TAG=v1.1.0
```

The target checks that the release and a nonempty MP4 exist, uploads the video,
and prints its download URL. The URL becomes public when the release is
published. Repeating the command replaces an existing asset with the same
filename. Update both video links at the top of this file when moving the demo
to a new release.
