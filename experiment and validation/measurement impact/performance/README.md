# Performance — isolated validation of R10

Validates the measurement of **ΔSize** on a single-stage Dockerfile of one
instruction, where the base image is the only thing that changes.

The scenario is deliberately minimal: both states hold a single `FROM` and
nothing else, so every delta the tool reports is attributable to the base image
and to no other instruction.

| | before | after |
|---|---|---|
| Dockerfile | `FROM debian:12-slim` | `FROM alpine:3.19` |

## Contents

| Path | Content |
|---|---|
| `validate_r10_isolated.sh` | builds the scenario and runs the tool |
| `r10_isolated_report/impact_report.json` | the structured result |
| `r10_isolated_report/human_readable_summary.txt` | the report as printed |
| `r10_isolated_report/raw_data/` | Trivy and Hadolint output, verbatim |

## Reproducing

Run **under WSL2 or Linux**. Where Docker Engine runs inside WSL2 it listens on
a socket inside that virtual machine, which a Windows Python interpreter cannot
reach.

Required beforehand: `git`, `python3` (3.12 or later), a running Docker daemon,
`docker buildx`, and the Python dependencies from the repository root:

```bash
pip install -r requirements.txt
```

Then, from anywhere:

```bash
bash validate_r10_isolated.sh
```

The script checks every precondition before it starts and refuses to run with a
message naming what is missing. It creates its throwaway Git repository under
`/var/tmp`, and writes the report **beside itself**, into
`r10_isolated_report/`, whatever directory it is invoked from. Each run rebuilds
the scenario and overwrites the report.

Hadolint and Trivy are not installed: they run as official containers, pulled on
first use, so the run needs network access.

## Recorded result

| Metric | before | after | delta |
|---|---:|---:|---:|
| Image size (bytes) | 28,234,415 | 3,421,731 | **−24,812,684** |
| CVEs (distinct) | 96 | 4 | −92 |
| Warnings (47-rule) | 0 | 0 | 0 |
| Logical instructions | 1 | 1 | 0 |

Refactoring detected: **R10 — Update Base Image**.

The commit identifiers in `impact_report.json` change on every run: the
repository is created from scratch each time, so the hashes are not stable
across executions and are not meant to be compared between them.

## Analysis

The reading of this result — what it establishes about the metric, how it
compares with the same refactoring applied to a build stage rather than to the
image that ships, and the bearing of the size reproducibility limitation on
deltas of this magnitude — is presented in the evaluation chapter of the
dissertation. This folder holds the evidence, not its interpretation.
