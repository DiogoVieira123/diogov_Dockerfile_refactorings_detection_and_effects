# Extended Catalog — Empirical Impact Measurement

15 controlled experiments measuring the real impact of the catalogue's
refactoring rules on image size, security and structure.

The literature does not quantify these impacts: the reference study (Ksontini et
al. 2025) either did not perform the refactoring in any setting, omitted it for
low occurrence, or reports no isolated measurement, and no peer-reviewed study
isolates the effect of the remaining rules. Each experiment produces first-hand
data for one rule, so that every cell of the impact mapping rests on a
measurement rather than on an assumption.

**Design, common to all 15.** Each experiment compares two functionally
equivalent states of a Dockerfile — `before` and `after` the refactoring — built
with `--no-cache` from a base image pinned by digest. Only the instructions
implementing the target refactoring differ between states; package set,
versions, file contents and resulting filesystem are identical.

**Indicators.** Every experiment records what it measured; the number of
indicators per experiment follows from what the rule can affect.

| Indicator | Tool | Unit |
|---|---|---|
| ΔSize | Docker daemon | bytes |
| ΔCVEs | Trivy (container) | distinct `VulnerabilityID`, final image |
| ΔWarnings | Hadolint (container) | findings within the 47-rule maintainability filter |
| ΔInstr | dockerfile-parse | logical instructions, COMMENT excluded |

Sign convention: `Δ = after − before`. A folder name ends with a dimension only
when the experiment targets that single dimension; the experiments that measure
all four indicators carry no dimension suffix.

Measured 2026-07-27 · docker=29.1.3 · trivy=0.72.0 · trivy-db=v2@2026-07-27T19:20:18Z · hadolint=2.14.0 · dockerfile-parse=2.0.1

## Experiments

| ID | Folder | Rule | Measured | Result |
|---|---|---|---|---|
| 01 | `experiment_01_R01_InlineRUN_Security` | R01 Inline RUN Instructions | ΔCVEs (Security) | 146 → 146 · **+0** |
| 02 | `experiment_02_R02_UpdateBaseImageTAG_Performance` | R02 Update Base Image TAG | ΔSize (Performance) | 41,593,622 → 29,748,045 · **−11,845,577** |
| 03 | `experiment_03_R03_AddENV_Performance` | R03 Add ENV Variable | ΔSize (Performance) | 3,632,570 → 3,632,744 · **+174** |
| 04 | `experiment_04_R04_AddARG_Performance` | R04 Add ARG Instruction | ΔSize (Performance) | 3,632,570 → 3,632,763 · **+193** |
| 05 | `experiment_05_R05_ExtractStage_Security` | R05 Extract Stage | ΔCVEs (Security) | 6,162 → 0 · **−6,162** |
| 06 | `experiment_06_R06_InlineStage` | R06 Inline Stage | ΔSize, ΔCVEs, ΔWarnings and ΔInstr, measured together | ΔSize 3,632,710 → 3,632,826 · **+116**<br>ΔCVEs 0 → 0 · **+0**<br>ΔWarnings 0 → 0 · **+0**<br>ΔInstr 8 → 5 · **−3** |
| 07 | `experiment_07_R07_SortInstructions_Security` | R07 Sort Instructions | ΔCVEs (Security) | 119 → 119 · **+0** |
| 08 | `experiment_08_R08_ReplaceADDwithCOPY_Performance` | R08 Replace ADD with COPY | ΔSize (Performance) | 3,632,098 → 3,632,099 · **+1** |
| 09 | `experiment_09_R09_ExtractRUN` | R09 Extract RUN Instructions | ΔSize, ΔCVEs, ΔWarnings and ΔInstr, measured together | ΔSize 3,633,775 → 3,634,192 · **+417**<br>ΔCVEs 0 → 0 · **+0**<br>ΔWarnings 0 → 0 · **+0**<br>ΔInstr 5 → 6 · **+1** |
| 10 | `experiment_10_R11_MoveStage` | R11 Move Stage | ΔSize, ΔCVEs, ΔWarnings and ΔInstr, measured together | ΔSize 3,632,724 → 3,632,725 · **+1**<br>ΔCVEs 0 → 0 · **+0**<br>ΔWarnings 0 → 0 · **+0**<br>ΔInstr 8 → 9 · **+1** |
| 11 | `experiment_11_R12_RemoveRUNmv` | R12 Remove RUN (mv command) | ΔSize, ΔCVEs, ΔWarnings and ΔInstr, measured together | ΔSize 3,634,927 → 3,633,596 · **−1,331**<br>ΔCVEs 0 → 0 · **+0**<br>ΔWarnings 0 → 0 · **+0**<br>ΔInstr 8 → 6 · **−2** |
| 12 | `experiment_12_R13_UpdateRUN_Performance` | R13 Update RUN Instruction | ΔSize (Performance) | 11,100,915 → 11,100,931 · **+16** |
| 13 | `experiment_13_R13_UpdateRUN_Security` | R13 Update RUN Instruction | ΔCVEs (Security) | 146 → 146 · **+0** |
| 14 | `experiment_14_R14_RenameImage_Performance` | R14 Rename Image | ΔSize (Performance) | 3,632,095 → 3,632,095 · **+0** |
| 15 | `experiment_15_R14_RenameImage_Security` | R14 Rename Image | ΔCVEs (Security) | 77 → 77 · **+0** |

Rules covered: R01–R09, R11–R14. R13 and R14 are each measured on two dimensions
(experiments 12/13 and 14/15). Experiments 06, 09, 10 and 11 record all four
indicators from a single run of the pair; the remaining experiments record the
indicator of the dimension they target, with the other values kept in the
folder's `result.txt` for the record.

### Base images

| Scope | Image |
|---|---|
| Experiments 03, 04, 06, 08, 09, 10, 11, 12, 14 | `alpine@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc` |
| Experiments 01, 07, 13, 15 | `debian@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818` |
| Experiment 02 | `ubuntu:latest` → `ubuntu:22.04` (tags; the mutable tag is the object of study) |
| Experiment 05 | `rust:1.78` builder → `alpine:3.20` runtime (tags; resolved digests in `result.txt`) |

Debian is used where the metric is ΔCVEs, because the pinned `alpine:3.20`
digest reports 0 vulnerabilities for every package set tested, which would make
an unchanged count indistinguishable from an absence of data. The Debian base
gives a non-zero baseline, so an unchanged count is a measurement (N → N).

## Replication

Every experiment uses the same entry point.

### Prerequisites

| Requirement | Notes |
|---|---|
| Docker | daemon running; verify with `docker info` |
| Python 3 | required by every experiment |
| `dockerfile-parse` | `pip install dockerfile-parse` |
| Network access | first run only, to pull the pinned base images and the `hadolint/hadolint` and `aquasec/trivy` images |

Trivy and Hadolint are not installed locally; they run as official containers.

### Command

```bash
cd experiment_01_R01_InlineRUN_Security
sh run_experiment.sh
```

The same two lines work in any of the 15 folders. Each `run_experiment.sh`
builds both states with `--no-cache` and prints the measurement; compare the
printed delta with the delta recorded in that folder's `result.txt`, or read the
`OK`/`DIFF` verdict where the script prints one.

### Pinning mechanisms

| Mechanism | Value / effect |
|---|---|
| Base image digest, Alpine | `alpine@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc` |
| Base image digest, Debian | `debian@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818` |
| Alpine package versions | `curl=8.14.1-r2`, `openssl=3.3.7-r0`, `git=2.45.4-r0`, `bash=5.2.26-r0`, `zlib=1.3.2-r0` |
| Debian package versions | `curl=7.88.1-10+deb12u15`, `openssl=3.0.20-1~deb12u2`, `git=1:2.39.5-0+deb12u3`, `zlib1g=1:1.2.13.dfsg-1`, `bash=5.2.15-2+b13` |
| Build flag | `--no-cache` on every build; no layer reuse |
| Apt index | `rm -rf /var/lib/apt/lists/*` in the same layer |
| Tool versions | recorded in every `result.txt` and `metrics_output.json` |

Both states of a pair install the identical package set; the only difference
between them is the refactoring under test.

### Constraints on reproduction

| Item | Behaviour |
|---|---|
| ΔCVEs | depends on the Trivy vulnerability database, republished daily. Absolute counts may change with a newer database; the delta holds, since both states are scanned in the same run against the same database. The database version is recorded with each measurement. |
| ΔSize | varies between runs due to image metadata (timestamps, layer descriptors). Re-running all 15 experiments on 2026-07-28 reproduced every ΔSize to within 22 bytes, and where the recorded delta is itself only a byte or two the sign can flip (experiment 10: +1 recorded, −1 on re-run). Deltas at this magnitude are metadata, not content; deltas of the order of kilobytes and above (experiments 02, 05, 11) reproduce with their sign and magnitude intact. |
| Experiment 02 | uses `ubuntu:latest`, a mutable tag, in the before state. Not reproducible by design; the resolved digest is recorded in `result.txt`. |
| Experiment 05 | pins by tag, not digest. Resolved digests are recorded in `result.txt`. |

### If a pinned package version is removed from the mirror

Builds fail with "version not found" once a security update supersedes a pinned
version. Two options:

1. Debian — point apt at the snapshot archive for a fixed date:
   ```dockerfile
   RUN echo 'deb http://snapshot.debian.org/archive/debian/20260727T000000Z bookworm main' \
       > /etc/apt/sources.list
   ```
2. Re-pin both states to the current version and re-measure the pair together.
   Absolute values will differ from those recorded here; never re-measure one
   side only.

## Folder contents

| File | Content |
|---|---|
| `Dockerfile.before`, `Dockerfile.after` | the two states; only the target refactoring differs |
| `run_experiment.sh` | replication entry point, identical name in every experiment |
| `result.txt` | recorded measurement, Reporting Template format |
| `metrics_output.json` | the four indicators in machine-readable form (experiments 06, 09, 10, 11) |
| `verify_catalog.py` | measurement script invoked by the runner (experiments 06, 09, 10, 11) |
| `hadolint-*.json`, `trivy-*.json`, `size-*.txt`, `logical-instructions-*.txt` | raw tool output per state (experiments 06, 09, 10, 11) |
| `README.md` | per-experiment description (experiments 06, 09, 10, 11) |
| support files | `app.sh`, `app.txt`, `app.conf`, `config.txt`, `entrypoint.sh`, `setup.sh` — copied by the builds |
| `log_before.txt`, `log_after.txt` | raw Trivy output (experiment 05) |

Experiment 05 uses the file names `R05_cargo_before.Dockerfile` and
`R05_cargo_after.Dockerfile`; experiment 10 adds `Dockerfile.builder` for the
extracted stage. Their `run_experiment.sh` refers to those names.
