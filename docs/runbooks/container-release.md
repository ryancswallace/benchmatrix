# Container release runbook

Use this when verifying or troubleshooting Docker image publication.

## Preconditions

* The repository package visibility allows publishing to GitHub Container
    Registry.
* The Docker workflow's release publication job has `packages: write`
    permission.
* A reviewed GitHub Release is ready to publish for a tag starting with `v`,
    such as `v1.1.0`.

## Normal release flow

1. Follow the release runbook through preparation and review of the draft
    GitHub Release.
2. Publish the reviewed GitHub Release. Pushing its tag or saving the release as
    a draft does not publish a container.
3. Watch the `Docker` workflow triggered by the release's `published` event.
4. Confirm the workflow:

    * lints `Dockerfile` and `.devcontainer/Dockerfile`;
    * builds and runs the test image;
    * builds and smoke-tests the runtime image;
    * scans both images with Trivy and fails on critical vulnerabilities;
    * publishes the runtime image to GHCR only after those checks pass;
    * emits Buildx SBOM and provenance attestations for the runtime image.

5. Open the GHCR package page and confirm these runtime image tags exist:

    * `ghcr.io/ryancswallace/benchmatrix:vX.Y.Z`;
    * `ghcr.io/ryancswallace/benchmatrix:latest`;
    * `ghcr.io/ryancswallace/benchmatrix:sha-<commit>`.

6. Verify the runtime image from GHCR:

    ```bash
    docker run --rm ghcr.io/ryancswallace/benchmatrix:vX.Y.Z --version
    ```

    The command should print `benchmatrix X.Y.Z`. Running the image with no
    arguments should display the command help. The internal test stage is not
    published.

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
* Publish failure: confirm GHCR package permissions, the publication job's
   `packages: write` permission, and that the GitHub Release uses a `v*` tag.
