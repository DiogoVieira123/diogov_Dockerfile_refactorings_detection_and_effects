# Experiment 1 — R06: Inline Stage

**Extended Catalog validation experiment**

## Objective

Measure the impact of the **R06 — Inline Stage** refactoring on the three quality
dimensions used in this dissertation (image size, maintainability, security), in the
absence of an empirical study in the literature that isolates this refactoring. Ksontini
et al. (2025) explicitly report that the Inline Stage refactoring "was not performed in
any setting" of their study, so no measured impact is available from the literature.

The refactoring merges or removes a stage of a multi-stage build when the separation
into multiple stages provides no benefit (i.e. when the extra stage produces no
build-only artifacts that need to be discarded), simplifying the Dockerfile structure.

## Method

Two functionally equivalent Dockerfiles are compared:

- `Dockerfile.before` — a multi-stage build with a `builder` stage that provides no
  benefit (both stages use the same base image and no build-only dependencies are
  discarded). Two `FROM` instructions.
- `Dockerfile.after` — the unnecessary stage is inlined into a single stage. Same
  functionality, one `FROM` instruction, no `COPY --from`.

Both images are built and measured on the three dissertation metrics:

| Metric | Tool | How |
|---|---|---|
| Image size (bytes) | Docker | `docker image inspect --format '{{.Size}}'` |
| Maintainability (Hadolint warnings) | `hadolint/hadolint` container | static analysis of the Dockerfile |
| Security (CVEs) | `aquasec/trivy` container | scan of the built image |
| Structure (stages + instructions) | static count | counts `FROM` stages and total instructions in each Dockerfile |

Hadolint and Trivy are executed as official Docker containers, consistent with the
Data Extractor component described in Section 5.7 of the dissertation. A fourth,
structural metric (number of stages and instructions) is included because Inline Stage
is not a Hadolint smell: its maintainability benefit lies in simplifying the Dockerfile
structure, which is captured by the reduction in stages and instructions rather than by
the Hadolint warning count.

## Reproducibility — how to replicate this experiment

**Prerequisites**

- A Linux host (this experiment was run on Ubuntu).
- Docker installed and running. Verify with `docker info`.
- Internet access (the first run pulls `alpine:3.20`, `hadolint/hadolint`
  and `aquasec/trivy`).

**Steps**

1. Place all the files of this folder in a single directory:
   `Dockerfile.before`, `Dockerfile.after`, `app.sh`, `measure.sh`.

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
   - a `--no-cache` build of both Dockerfiles;
   - the three measurements (image size, Hadolint warnings, Trivy CVEs) on each state;
   - the computation of the Delta (AFTER - BEFORE) for each metric.

5. The results are printed to the terminal and written to `output.txt`.

**Notes for an exact replication**

- The base image is pinned to `alpine:3.20`.
- `--no-cache` is used so that the measured sizes are not affected by a warm cache.
- The two Dockerfiles are functionally equivalent (same final filesystem and same
  `CMD`); only the multi-stage structure differs. This isolates the effect of the
  refactoring.

## Files

| File | Description |
|---|---|
| `Dockerfile.before` | State before the refactoring (unnecessary multi-stage) |
| `Dockerfile.after`  | State after the refactoring (single inlined stage) |
| `app.sh`            | Sample application script used by the build |
| `measure.sh`        | Measurement script (3 metrics) |
| `output.txt`        | Raw measurement results produced by the script |

## Results

Measured on 2026-06-29 (Ubuntu, base image `alpine:3.20`):

| Metric | Before | After | Delta |
|---|---|---|---|
| Image size (bytes) | 3 632 710 | 3 632 827 | +117 |
| Hadolint warnings  | 0 (no warnings) | 0 (no warnings) | 0 |
| CVEs               | 0 | 0 | 0 |

## Conclusion

Inlining the unnecessary build stage left the three metrics without regression: the image
size varied by only +117 bytes (a negligible difference attributable to image metadata,
since both Dockerfiles produce the same final filesystem), with no Hadolint warnings in
either state and no CVEs. The experiment confirms that R06 introduces no regression in
performance, smells, or security. Its benefit lies in maintainability — removing a
redundant `FROM` and a `COPY --from` produces a simpler, single-stage Dockerfile — which
is argued from the nature of the operation rather than claimed as a measured improvement,
since this structural simplicity is not captured by the three automatic metrics.
