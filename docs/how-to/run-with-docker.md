# Run with Docker

benchmatrix is distributed primarily as a Python package. The runtime container
is a convenience for isolated comparisons and CI jobs that do not need a Python
installation on the host.

## Images

The repository publishes one image:

* `ghcr.io/ryancswallace/benchmatrix` is the runtime image. It installs the
    package with runtime dependencies only. It runs the `benchmatrix` command
    and displays CLI help when no arguments are provided.

The Dockerfile also has a `test` build stage with the project's development and
release tooling. CI and local checks build and scan that stage, but it is not
published as a user-facing image. Both stages run as a non-root user.

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

Check the installed version:

```bash
docker run --rm ghcr.io/ryancswallace/benchmatrix:latest --version
```

Arguments after the image name are passed directly to `benchmatrix`. To compare
collections from the current directory:

```bash
docker run --rm \
    --mount type=bind,source="$PWD",target=/work,readonly \
    --workdir /work \
    ghcr.io/ryancswallace/benchmatrix:latest \
    compare demo-baseline demo-candidate --fail-on-regression
```

Use a version tag such as `v1.1.0` instead of `latest` when a workflow needs a
reproducible tool version.

## Tag policy

Pull requests, pushes to `main`, and manual workflow runs build, test, and scan
the container stages without publishing them. Publishing a GitHub Release whose
tag starts with `v` publishes the runtime image with `vX.Y.Z`, `sha-*`, and
`latest` tags. Pushing a tag or creating a draft release does not publish an
image or move `latest`. The test stage is never published.

## Vulnerability scanning

The Docker workflow scans both the runtime image and internal test stage with
Trivy and fails on critical vulnerabilities. A release image is published only
after both scans pass. This keeps the first policy strict enough to catch urgent
image risk without making normal development noisy for lower-severity base image
findings.

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
