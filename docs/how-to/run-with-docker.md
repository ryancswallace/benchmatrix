# Run with Docker

benchmatrix is distributed primarily as a Python package. The Docker images are
convenience images for reproducible local use, CI smoke checks, and examples.

## Images

The repository builds two images:

* `ghcr.io/ryancswallace/benchmatrix` is the runtime image. It installs the
    package with runtime dependencies only and defaults to a safe import smoke
    test.
* `ghcr.io/ryancswallace/benchmatrix-test` is the test image. It includes the
    project test and release tooling and defaults to `python -m pytest -q`.

Both images run as a non-root user.

## Build locally

Build the runtime image:

```bash
make docker-build
```

Run the runtime smoke test:

```bash
make docker-smoke
```

Build and run the test image:

```bash
make docker-test
```

Run the full local Docker validation path:

```bash
make docker-check
```

`make docker-check` lints Dockerfiles, builds both images, runs the test image,
smoke-tests the runtime image, and scans both images for critical vulnerabilities.
It requires Docker. Inside the project devcontainer, rebuild the devcontainer so
the Docker-outside-of-Docker feature can provide the Docker CLI and host Docker
socket access.

Override the local image tag when needed:

```bash
IMAGE_TAG=my-check make docker-build docker-smoke
```

## Run a published image

After container publishing is enabled and a release has been published, run:

```bash
docker run --rm ghcr.io/ryancswallace/benchmatrix:latest
```

The default command should print `BenchmarkCase`. To run a custom command:

```bash
docker run --rm ghcr.io/ryancswallace/benchmatrix:latest \
    python -c "from benchmatrix import BenchmarkCase; print(BenchmarkCase.__name__)"
```

## Tag policy

Pull requests build and test images but do not push them. Pushes to `main` push
`main` and `sha-*` tags. Release tags matching `v*` push `vX.Y.Z`, `sha-*`, and
`latest` tags.

## Vulnerability scanning

The Docker workflow scans both runtime and test images with Trivy and fails on
critical vulnerabilities. This keeps the first policy strict enough to catch
urgent image risk without making normal development noisy for lower-severity base
image findings.

To scan locally, run:

```bash
make docker-scan
```

`make docker-scan` uses a local `trivy` executable when one is available. If not,
it runs the pinned `$(TRIVY_IMAGE)` container through Docker. The fallback scanner
mounts `$(DOCKER_SOCKET)`, which defaults to `/var/run/docker.sock`; set
`DOCKER_SOCKET=/path/to/docker.sock` when using a nonstandard or rootless Docker
socket.

To adjust the threshold, edit `.github/workflows/docker.yml` for CI and the
`docker-scan` target in `Makefile` for local scans. For example, use
`HIGH,CRITICAL` to fail on both high and critical vulnerabilities, or remove
`ignore-unfixed: true` if unfixed findings should fail the workflow.
