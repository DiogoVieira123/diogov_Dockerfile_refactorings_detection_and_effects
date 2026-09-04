# Maintainability — validation of ΔWarnings and ΔInstr

Validates the two maintainability metrics in a single run, on a Dockerfile that
carries two defects at once and has both corrected in the same commit.

| | before | after |
|---|---|---|
| Base image | `FROM ubuntu:latest` | `FROM ubuntu:22.04` |
| Commands | two separate `RUN` instructions | one chained `RUN` |

The mutable tag is what Hadolint reports as **DL3007**, and the consecutive
`RUN` instructions are what it reports as **DL3059**. Correcting both applies
two catalogue refactorings together — **R02** on the tag and **R01** on the
instructions — so the commit exercises the warning count and the logical
instruction count at the same time, and tests that neither detection masks the
other.

## Contents

| Path | Content |
|---|---|
| `run_maintenance_validation.sh` | builds the scenario and runs the tool |
| `maintenance_validation_report/impact_report.json` | the structured result |
| `maintenance_validation_report/human_readable_summary.txt` | the report as printed |
| `maintenance_validation_report/raw_data/hadolint_raw.json` | the linter output, verbatim |
| `maintenance_validation_report/raw_data/trivy_raw.json` | the scanner output, verbatim |

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
bash run_maintenance_validation.sh
```

The script checks every precondition before it starts and refuses to run with a
message naming what is missing. It creates its throwaway Git repository at
`/var/tmp/docker_validation`, and writes the report **beside itself**, into
`maintenance_validation_report/`, whatever directory it is invoked from. Each
run rebuilds the scenario and overwrites the report.

Hadolint and Trivy are not installed: they run as official containers, pulled on
first use, so the run needs network access.

## Recorded result

| Metric | before | after | delta |
|---|---:|---:|---:|
| Warnings (47-rule) | 2 | 1 | **−1** |
| Logical instructions | 3 | 2 | **−1** |
| CVEs (distinct) | 58 | 30 | −28 |
| Image size (bytes) | 78,803,270 | 86,417,330 | +7,614,060 |

Refactorings detected: **R01 — Inline RUN Instructions** and **R02 — Update Base
Image TAG**.

Two points to read carefully when inspecting `raw_data/hadolint_raw.json`:

**The linter emits more codes than the metric counts.** Hadolint reports
`DL3007, DL3008, DL3009, DL3015, DL3059` on the before state and
`DL3008, DL3009, DL3015` on the after — two disappear, yet the delta is −1. The
metric counts only the rules on the 47-rule screen, which is why the before
count is 2 rather than 5. The raw file is what makes this reconcilable.

**The size delta is positive.** `ubuntu:latest` currently resolves to a release
later than 22.04, so pinning the tag moves to a smaller version number and a
larger image. This is the real effect of the refactoring in this environment,
not an artefact.

The commit identifiers in `impact_report.json` change on every run: the
repository is created from scratch each time, so the hashes are not stable
across executions.

## Analysis

The reading of this result — what the divergence between emitted codes and
counted warnings establishes about the screening requirement, and how a
maintainability gain that costs image size bears on the classification of the
catalogue — is presented in the evaluation chapter of the dissertation. This
folder holds the evidence, not its interpretation.
