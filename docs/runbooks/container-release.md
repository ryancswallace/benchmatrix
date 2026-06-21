# Container release runbook

Use this when verifying or troubleshooting Docker image publication.

## Preconditions

* The repository package visibility allows publishing to GitHub Container
  Registry.
* The Docker workflow has `packages: write` permission on non-pull-request runs.
* The release tag starts with `v`, such as `v0.2.0`.

## Normal release flow

1. Publish the Python package release using the release runbook.
2. Watch the `Docker` workflow for the release tag.
3. Confirm the workflow:

   * lints `Dockerfile` and `.devcontainer/Dockerfile`;
   * builds and runs the test image;
   * builds and smoke-tests the runtime image;
   * scans both images with Trivy and fails on critical vulnerabilities;
   * publishes runtime and test images to GHCR;
   * emits Buildx SBOM and provenance attestations.

4. Open the GHCR package page and confirm these images exist:

   * `ghcr.io/ryancswallace/benchmatrix:vX.Y.Z`;
   * `ghcr.io/ryancswallace/benchmatrix:latest`;
   * `ghcr.io/ryancswallace/benchmatrix-test:vX.Y.Z`;
   * `ghcr.io/ryancswallace/benchmatrix-test:latest`.

5. Verify the runtime image from GHCR:

   ```bash
   docker run --rm ghcr.io/ryancswallace/benchmatrix:vX.Y.Z
   ```

   The command should print `BenchmarkCase`.

6. Verify the test image if the release changed packaging, dependencies, or test
   infrastructure:

   ```bash
   docker run --rm ghcr.io/ryancswallace/benchmatrix-test:vX.Y.Z
   ```

## Adjusting vulnerability policy

The Docker workflow currently fails on `CRITICAL` vulnerabilities and ignores
unfixed findings. To ratchet the policy, update the Trivy steps in
`.github/workflows/docker.yml`:

* change `severity: CRITICAL` to `severity: HIGH,CRITICAL` to fail on high and
  critical vulnerabilities;
* change `ignore-unfixed: true` to `ignore-unfixed: false` to include unfixed
  findings.

After changing the policy, run the Docker workflow on a pull request and confirm
that findings are actionable before making the check required.

## Failure handling

* Dockerfile lint failure: run `make docker-lint`, fix the Dockerfile, and rerun.
* Build failure: rebuild the devcontainer if needed, then run `make docker-check`
  locally when Docker is available.
* Runtime smoke failure: inspect the image command and package installation
  layer.
* Critical vulnerability: run `make docker-scan` locally to reproduce, then
  update the base image or affected dependency. If no fix is available, document
  the risk before temporarily relaxing the policy.
* Publish failure: confirm GHCR package permissions and workflow `packages:
  write` permissions.
