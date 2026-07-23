# Extended Catalog — Experimental Validation

This folder contains four controlled experiments that characterize the impact of four
Dockerfile refactorings of the extended catalog for which **no empirical measurement is
available in the literature**. For these refactorings, either the reference study
(Ksontini et al. 2025) explicitly did not measure them, or no peer-reviewed study isolates
their effect. Each experiment was therefore designed and run to provide first-hand evidence.

## Refactorings covered

| # | Folder | Refactoring | Why an experiment |
|---|---|---|---|
| 1 | `experiment_1_R06_inline_stage` | R06 — Inline Stage | Ksontini 2025 reports it "was not performed in any setting" |
| 2 | `experiment_2_R09_extract_run`  | R09 — Extract RUN Instructions | Ksontini 2025 omitted it (present in only 2 Dockerfiles) |
| 3 | `experiment_3_R11_move_stage`   | R11 — Move Stage | Ksontini 2025 omitted it (present in only 2 Dockerfiles) |
| 4 | `experiment_4_R12_remove_run_mv`| R12 — Remove RUN Instruction (mv) | No empirical study isolates it |

## Method (common to all four)

Each experiment compares two functionally equivalent states of a Dockerfile — `before` and
`after` the refactoring — built with the pinned base image `alpine:3.20`, and measures the
three quality metrics used throughout the dissertation:

1. **Image size** (bytes) — `docker image inspect`
2. **Maintainability as smells** — Hadolint warnings total: the count of
   findings within the unified maintainability filter (47 rules drawn from the
   maintainability categories of the Hadolint wiki — reproducibility,
   structural correctness, usage and notation, metadata, shell SC2046/SC2086,
   and logs DL3047 — identical across every verification script)
3. **Security** — CVEs reported by Trivy

Hadolint and Trivy are run as official Docker containers (`hadolint/hadolint`,
`aquasec/trivy`), consistent with the Data Extractor described in Section 5.7 of the
dissertation. Each experiment folder contains a `measure.sh` script, the Dockerfiles, the
support files, an `output.txt` with the raw results, and a `README.md` with full
replication instructions.

## Interpretation

The three metrics establish the **impact profile** of each refactoring: they identify the
dimension where a measurable benefit occurs and confirm the absence of regression in the
others. A null result (Delta = 0) is itself evidence — it shows the refactoring does not
degrade that dimension.

- **R12** shows a **measured benefit** in performance (image size reduced by 1 332 bytes).
- **R06, R09, R11** show **no regression** in any of the three metrics; their benefit is in
  maintainability (structural simplicity / readability), which is argued from the nature of
  each operation, since it is not captured by automatic size/smell/CVE metrics.

## Summary of results

| Refactoring | Image size (Delta) | Warnings total (maintainability filter) | CVEs | Logical instructions | Measured benefit |
|---|---|---|---|---|---|
| R06 Inline Stage | +116 B | 0 -> 0 | 0 -> 0 | 8 -> 5 (-3) | none measurable on size, CVEs or warnings; structural reduction |
| R09 Extract RUN Instructions | +417 B | 0 -> 0 | 0 -> 0 | 5 -> 6 (+1) | none measurable; structural cost of the extraction |
| R11 Move Stage | +1 B | 0 -> 0 | 0 -> 0 | 8 -> 9 (+1) | none measurable; modularisation cost across two files |
| R12 Remove RUN | -1,331 B | 0 -> 0 | 0 -> 0 | 8 -> 6 (-2) | performance/size |

## How to replicate

Each experiment is self-contained. From any experiment folder:

```bash
bash measure.sh
```

See the `README.md` inside each folder for prerequisites and exact steps. All experiments
were run on Ubuntu with Docker installed.
