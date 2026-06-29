# Experiment 3 — R11: Move Stage

**Extended Catalog validation experiment**

## Objective

Characterize the impact of the **R11 — Move Stage** refactoring on the three quality
dimensions used in this dissertation, in the absence of an empirical study in the
literature that isolates this refactoring. Ksontini et al. (2025) omitted this
refactoring from their study because it was present in only two Dockerfiles, so no
measured impact is available from the literature.

The refactoring extracts an entire build stage out of a multi-stage Dockerfile into its
own standalone, independent Dockerfile (for example, isolating a build or test stage into
a separate file that can be built independently and reused as a pre-built base image).

## Method

- `Dockerfile.before` — a single multi-stage Dockerfile with a `builder` stage and the
  final runtime stage.
- `Dockerfile.builder` — the build stage **moved out** into its own standalone Dockerfile,
  built separately and tagged `r11-builder`.
- `Dockerfile.after` — the main Dockerfile, which no longer contains the build stage and
  instead uses the separately-built `r11-builder` image.

Both states are built and measured on the three dissertation metrics:

| Metric | Tool | How |
|---|---|---|
| Image size (bytes) | Docker | `docker image inspect --format '{{.Size}}'` (final runtime image) |
| Maintainability (Hadolint warnings) | `hadolint/hadolint` container | static analysis of the Dockerfile(s) |
| Security (CVEs) | `aquasec/trivy` container | scan of the built runtime image |

These three metrics establish whether the refactoring introduces any **regression** in
performance (size), smells (Hadolint), or security (CVEs). For the AFTER state, the
Hadolint count is the sum of the main and the extracted builder Dockerfiles, since the
logic now lives in two files. The maintainability benefit of this refactoring — isolating
a stage into a reusable, independent Dockerfile — is argued from the nature of the
operation in the dissertation text, and is **not** claimed here as a measured improvement.

Hadolint and Trivy are executed as official Docker containers, consistent with the Data
Extractor component described in Section 5.7 of the dissertation.

## Reproducibility — how to replicate this experiment

**Prerequisites**

- A Linux host (this experiment was run on Ubuntu).
- Docker installed and running. Verify with `docker info`.
- Internet access (the first run pulls `alpine:3.20`, `hadolint/hadolint`,
  and `aquasec/trivy`).

**Steps**

1. Place all the files of this folder in a single directory:
   `Dockerfile.before`, `Dockerfile.after`, `Dockerfile.builder`, `app.txt`, `measure.sh`.

2. Open a terminal in that directory.

3. Run the measurement script:
   ```bash
   bash measure.sh
   ```
   If Docker requires elevated privileges on your host, run instead:
   ```bash
   sudo bash measure.sh
   ```

4. The script performs, automatically:
   - a `--no-cache` build of the BEFORE multi-stage Dockerfile;
   - a `--no-cache` build of the extracted builder (`Dockerfile.builder`, tagged
     `r11-builder`), followed by the main AFTER Dockerfile that uses it;
   - the three measurements on each state;
   - the computation of the Delta (AFTER - BEFORE) for each metric.

5. The results are printed to the terminal and written to `output.txt`.

**Notes for an exact replication**

- The base image is pinned to `alpine:3.20`.
- `--no-cache` is used so that the measured sizes are not affected by a warm cache.
- In the AFTER state the build stage is built first as a standalone image
  (`r11-builder`); the main image then consumes it. The two states are functionally
  equivalent (same final `artifact.txt` and same `CMD`).
- The Hadolint count for the AFTER state sums the warnings of the main and the builder
  Dockerfiles, since the refactoring splits the logic across two files.

## Files

| File | Description |
|---|---|
| `Dockerfile.before`  | State before (single multi-stage Dockerfile) |
| `Dockerfile.builder` | The build stage moved into its own standalone Dockerfile |
| `Dockerfile.after`   | The main Dockerfile after the stage was moved out |
| `app.txt`            | Sample data file used by the build |
| `measure.sh`         | Measurement script (3 metrics) |
| `output.txt`         | Raw measurement results produced by the script |

## Results

Measured on 2026-06-29 (Ubuntu, base image `alpine:3.20`):

| Metric | Before | After | Delta |
|---|---|---|---|
| Image size (bytes) | 3 632 724 | 3 632 725 | +1 |
| Hadolint warnings (main + builder) | 0 (no warnings) | 0 (no warnings) | 0 |
| CVEs               | 0 | 0 | 0 |

## Conclusion

Moving the build stage out into its own standalone Dockerfile (`Dockerfile.builder`,
tagged `r11-builder:1.0`) and referencing it from the main Dockerfile left the final
runtime image essentially identical (+1 byte), with no Hadolint warnings in either state
(main and builder combined) and no CVEs. The experiment confirms that R11 introduces no
regression in performance, smells, or security. Its benefit lies in maintainability —
isolating a stage into a reusable, independent Dockerfile modularizes the build process —
which is argued from the nature of the operation rather than claimed as a measured
improvement, since this modularization is not captured by the three automatic metrics.

Note: the extracted image is referenced with an explicit tag (`r11-builder:1.0`) so that
no version-pinning warning (DL3006) is introduced. Referencing the extracted image is
inherent to this refactoring, and pinning its version keeps the practice clean.
