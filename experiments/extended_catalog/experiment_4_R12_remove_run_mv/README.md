# Experiment 4 — R12: Remove RUN Instruction (mv command)

**Extended Catalog validation experiment**

## Objective

Measure the impact of the **R12 — Remove RUN Instruction (mv command)** refactoring
on the three quality dimensions used in this dissertation (image size, maintainability,
security), in the absence of an empirical study in the literature that isolates this
specific refactoring.

The refactoring removes a `RUN` instruction whose only purpose is to run an `mv`
command, configuring the correct destination path directly in the preceding
`COPY` (or `ADD`) instruction. This eliminates the extra image layers that the
`RUN mv` instructions create.

## Method

Two functionally equivalent Dockerfiles are compared:

- `Dockerfile.before` — copies each file to a temporary path, then uses a separate
  `RUN mv` to move it to its final destination (3 `RUN` instructions, 2 of them `mv`).
- `Dockerfile.after` — copies each file directly to its final destination in the
  `COPY` instruction, with no `RUN mv` (1 `RUN` instruction).

Both images are built and measured on the three dissertation metrics:

| Metric | Tool | How |
|---|---|---|
| Image size (bytes) | Docker | `docker image inspect --format '{{.Size}}'` |
| Maintainability (Hadolint warnings) | `hadolint/hadolint` container | static analysis of the Dockerfile |
| Security (CVEs) | `aquasec/trivy` container | scan of the built image |
| Structure (stages + instructions) | static count | counts `FROM` stages and total instructions in each Dockerfile |

Hadolint and Trivy are executed as official Docker containers, consistent with the
Data Extractor component described in Section 5.7 of the dissertation. This keeps the
tool versions pinned and avoids host-level installation differences. A fourth, structural
metric (stages and instructions) is included for consistency across all extended-catalog
experiments; for R12 it captures the removal of the two `RUN mv` instructions.

## Reproducibility — how to replicate this experiment

Anyone can replicate this experiment by following these exact steps.

**Prerequisites**

- A Linux host (this experiment was run on Ubuntu).
- Docker installed and running. Verify with `docker info`.
- Internet access (the first run pulls the `alpine:3.20`, `hadolint/hadolint`
  and `aquasec/trivy` images).

**Steps**

1. Place all the files of this folder in a single directory:
   `Dockerfile.before`, `Dockerfile.after`, `app.conf`, `entrypoint.sh`, `measure.sh`.

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
   - a `--no-cache` build of both Dockerfiles (so the measurement is not affected
     by cached layers);
   - the three measurements (image size, Hadolint warnings, Trivy CVEs) on each state;
   - the computation of the Delta (AFTER - BEFORE) for each metric.

5. The results are printed to the terminal and written to `output.txt`.

**Notes for an exact replication**

- The base image is pinned to `alpine:3.20`. Using a different base image (or a
  `latest` tag) may change the absolute size and CVE numbers, although the direction
  of the size Delta (a reduction) is expected to hold, since the refactoring removes
  image layers.
- `--no-cache` is used on purpose: building with a warm cache would report
  inconsistent sizes between runs.
- The two Dockerfiles are functionally equivalent (same final filesystem layout and
  same `CMD`); only the way files reach their destination differs. This isolates the
  effect of the refactoring.

## Files

| File | Description |
|---|---|
| `Dockerfile.before` | State before the refactoring (with `RUN mv`) |
| `Dockerfile.after`  | State after the refactoring (no `RUN mv`) |
| `app.conf`          | Sample config file used by the build |
| `entrypoint.sh`     | Sample entrypoint script used by the build |
| `measure.sh`        | Measurement script (3 metrics) |
| `output.txt`        | Raw measurement results produced by the script |

## Results

Measured on 2026-06-29 (Ubuntu, base image `alpine:3.20`):

| Metric | Before | After | Delta |
|---|---|---|---|
| Image size (bytes) | 3 634 926 | 3 633 594 | **-1 332** |
| Hadolint warnings  | 0 (no warnings) | 0 (no warnings) | 0 |
| CVEs               | 0 | 0 | 0 |

## Conclusion

Removing the two `RUN mv` instructions and configuring the destination path directly in
the `COPY` instructions produced a **measured reduction in image size of 1 332 bytes** (by
eliminating the two extra layers the `RUN mv` instructions created), with no Hadolint
warnings in either state and no CVEs. The experiment demonstrates a direct, measured
benefit in the performance/size dimension, with no regression in maintainability or
security. The magnitude depends on the files being moved; with small files the saving is
the layer overhead removed, and it is expected to be larger for bigger files or
directories, since the moved data would otherwise be duplicated across the temporary and
final layers.
