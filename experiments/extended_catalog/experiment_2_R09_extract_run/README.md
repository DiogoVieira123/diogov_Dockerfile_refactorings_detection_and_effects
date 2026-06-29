# Experiment 2 — R09: Extract RUN Instructions

**Extended Catalog validation experiment**

## Objective

Characterize the impact of the **R09 — Extract RUN Instructions** refactoring on the
three quality dimensions used in this dissertation (performance/size, maintainability,
security), in the absence of an empirical study in the literature that isolates this
refactoring. Ksontini et al. (2025) omitted this refactoring from their study because it
was present in only two Dockerfiles, so no measured impact is available from the
literature.

The refactoring moves a complex sequence of shell commands out of a `RUN` instruction
and into an external script file (`setup.sh`), which is copied into the image and
executed, keeping the Dockerfile cleaner.

## Method

Two functionally equivalent Dockerfiles are compared:

- `Dockerfile.before` — a single `RUN` instruction with seven shell commands chained
  inline with `&&`.
- `Dockerfile.after` — the shell logic is extracted to `setup.sh`; the Dockerfile copies
  the script and runs it.

Both images are built and measured on the three dissertation metrics:

| Metric | Tool | How |
|---|---|---|
| Image size (bytes) | Docker | `docker image inspect --format '{{.Size}}'` |
| Maintainability (Hadolint warnings) | `hadolint/hadolint` container | static analysis of the Dockerfile |
| Security (CVEs) | `aquasec/trivy` container | scan of the built image |

These three metrics establish whether the refactoring introduces any **regression** in
performance (size), smells (Hadolint), or security (CVEs). The maintainability benefit of
this refactoring — moving complex shell logic out of the Dockerfile — is not captured by
these automatic metrics; it is argued from the nature of the operation in the dissertation
text, and is **not** claimed here as a measured improvement.

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
   `Dockerfile.before`, `Dockerfile.after`, `app.txt`, `setup.sh`, `measure.sh`.

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
   - the three measurements on each state;
   - the computation of the Delta (AFTER - BEFORE) for each metric.

5. The results are printed to the terminal and written to `output.txt`.

**Notes for an exact replication**

- The base image is pinned to `alpine:3.20`.
- `--no-cache` is used so that the measured sizes are not affected by a warm cache.
- The two Dockerfiles are functionally equivalent: both produce the same
  `/app/data/app.txt` and the same `CMD`. Only the location of the shell logic differs
  (inline RUN vs. external `setup.sh`). This isolates the effect of the refactoring.
- `setup.sh` contains exactly the same commands that were inline in `Dockerfile.before`.

## Files

| File | Description |
|---|---|
| `Dockerfile.before` | State before (complex inline RUN) |
| `Dockerfile.after`  | State after (logic extracted to `setup.sh`) |
| `app.txt`           | Sample data file used by the build |
| `setup.sh`          | The extracted shell logic |
| `measure.sh`        | Measurement script (3 metrics) |
| `output.txt`        | Raw measurement results produced by the script |

## Results

Measured on 2026-06-29 (Ubuntu, base image `alpine:3.20`):

| Metric | Before | After | Delta |
|---|---|---|---|
| Image size (bytes) | 3 633 773 | 3 634 183 | +410 |
| Hadolint warnings  | 0 (no warnings) | 0 (no warnings) | 0 |
| CVEs               | 0 | 0 | 0 |

## Conclusion

Extracting the complex inline `RUN` (six chained shell commands) into an external
`setup.sh` left the three metrics without regression: the image size varied by only +410
bytes (the added script file), with no Hadolint warnings in either state and no CVEs. The
experiment confirms that R09 introduces no regression in performance, smells, or security.
Its benefit lies in maintainability — moving complex shell logic out of the Dockerfile
keeps the main file cleaner and easier to read — which is argued from the nature of the
operation rather than claimed as a measured improvement, since this readability gain is
not captured by the three automatic metrics.
