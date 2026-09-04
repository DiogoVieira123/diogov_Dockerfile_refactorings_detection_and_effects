# Security — end-to-end validation of ΔCVEs

Validates the measurement of **ΔCVEs** and its stratification by severity, on a
Node application whose Dockerfile moves from a Debian base to an Alpine base.

The Node version is held constant across both states. Only the base operating
system changes, so the reduction cannot be attributed to a runtime upgrade:

| | before | after |
|---|---|---|
| Base image | `node:18.16.0` | `node:18.16.0-alpine` |
| Application | `app.js`, unchanged | `app.js`, unchanged |

## Contents

| Path | Content |
|---|---|
| `security_validation.sh` | builds the scenario and runs the tool |
| `security_validation_report/impact_report.json` | the structured result |
| `security_validation_report/human_readable_summary.txt` | the report as printed |
| `security_validation_report/raw_data/trivy_raw.json` | the scanner output, verbatim |
| `security_validation_report/raw_data/hadolint_raw.json` | the linter output, verbatim |

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
bash security_validation.sh
```

The script checks every precondition before it starts and refuses to run with a
message naming what is missing. It creates its throwaway Git repository under
`/var/tmp`, and writes the report **beside itself**, into
`security_validation_report/`, whatever directory it is invoked from. Each run
rebuilds the scenario and overwrites the report.

Both base images are pulled if absent, roughly 1 GB on a cold cache. Hadolint
and Trivy are not installed either: they run as official containers, so the run
needs network access.

## Recorded result

| Metric | before | after | delta |
|---|---:|---:|---:|
| CVEs (distinct) | 8,940 | 49 | **−8,891** |
| Image size (bytes) | 396,508,032 | 53,229,248 | −343,278,784 |
| Warnings (47-rule) | 0 | 0 | 0 |
| Logical instructions | 4 | 4 | 0 |

Net change by severity:

| Severity | before | after | delta |
|---|---:|---:|---:|
| CRITICAL | 56 | 2 | −54 |
| HIGH | 1,894 | 21 | −1,873 |
| MEDIUM | 5,991 | 15 | −5,976 |
| LOW | 954 | 11 | −943 |
| UNKNOWN | 45 | 0 | −45 |

Refactoring detected: **R02 — Update Base Image TAG**.

Every vulnerability behind these counts appears in `raw_data/trivy_raw.json`
with its identifier and severity, so any figure above can be traced to the
scanner output that produced it. Counts move with the Trivy vulnerability
database, whose version is recorded in the `environment` block of the report; a
run on a later database will not reproduce the figures exactly.

## Analysis

The reading of this result — what it establishes about the metric and its
stratification, and why a scan count is a measure of what the scanner reports
rather than of risk in the abstract — is presented in the evaluation chapter of
the dissertation. This folder holds the evidence, not its interpretation.
