# Dockerfile Refactorings: Detection and Effects

Supporting repository for the MSc dissertation "Dockerfile Refactorings: Detection and Effects", developed at the Instituto Superior de Engenharia do Porto (ISEP).

**Author:** Diogo Pereira Vieira
**Supervisor:** Prof. Isabel Azevedo
**Programme:** MSc in Computer Engineering, specialization in Cybersecurity and Systems Administration

## About

The dissertation proposes an extended catalogue of Dockerfile refactorings classified by quality dimension (performance, security, maintainability), and a Python prototype that automatically detects refactorings between two versions of a Dockerfile and measures their impact across four metrics: image size in bytes, vulnerability count (CVEs), linter warnings, and logical instruction count.

This repository holds the prototype, the empirical material that supports the
design described in Chapter 5, and the literature review replication package.

The prototype runs as a four-stage pipeline: data collection from the Git
history, refactoring detection, empirical evaluation and measurement, and
report generation. Detection is deterministic and reads structure alone —
it never consults the catalogue or any expected answer.

## Structure

| Path | Content |
|---|---|
| `src/` | the prototype: one module per pipeline component |
| `tests/` | the test suite |
| `main.py` | command-line entry point |
| `experiments/` | empirical material supporting Chapter 5 |
| `experiments/extended_catalog/` | 15 experiments measuring the impact of the catalogue's rules |
| `literature-review/` | PRISMA replication package: raw database exports, screening scripts and logs |
| `DESIGN_CHAPTER.md` | Chapter 5 — design of the prototype |
| `PROJECT_CONTEXT.md` | architecture and technology constraints |
| `requirements.txt` | Python dependencies |
| `conftest.py` | empty by design: its presence puts the repository root on `sys.path` for pytest |

## Rapid experiments

Five experiments (Table 5.1), each validating the technical feasibility of one prototype component before the design was finalised.

| # | Folder | Validated component |
|---|---|---|
| Exp 1 | `experiments/exp1-poc-refactorings/` | Three-metric measurement principle (four proof-of-concept refactorings) |
| Exp 2 | `experiments/exp2-hadolint-trivy-schemas/` | Data Extractor (Hadolint and Trivy JSON schemas) |
| Exp 3 | `experiments/exp3-gitpython-vcs/` | VCS Connector (GitPython) |
| Exp 4 | `experiments/exp4-docker-sdk-size/` | Performance Analyzer (Docker SDK) |
| Exp 5 | `experiments/exp5-dockerfile-parse-detection/` | Detection Engine (dockerfile-parse) |

## Extended catalog

`experiments/extended_catalog/` holds 15 experiments measuring the impact of the catalogue's refactoring rules on image size, security and structure, covering R01–R09 and R11–R14 (R13 and R14 on two dimensions each). They provide first-hand data for rules the literature does not quantify.

Each experiment compares two functionally equivalent Dockerfile states, built with `--no-cache` from a base image pinned by digest, with package versions pinned so that the only difference between states is the refactoring under test. Every experiment is reproduced with the same command from inside its folder:

```bash
sh run_experiment.sh
```

See `experiments/extended_catalog/README.md` for the experiment table, recorded values, prerequisites and pinning mechanisms.

## Literature review

`literature-review/` contains the PRISMA replication package: the raw exports from IEEE Xplore, ACM and SpringerLink, the screening scripts, and the logs recording identified records, duplicates, exclusions and included studies.

## Tools used

| Tool | Purpose |
|---|---|
| Hadolint | Dockerfile linter (warnings) |
| Trivy | vulnerability scanner (CVEs) |
| Docker SDK for Python | image size in bytes |
| GitPython | Git history access |
| dockerfile-parse | logical instruction parsing |

Hadolint and Trivy run as official Docker containers, so no local installation of either is required.

## Reproducing the experiments

Requirements: a running Docker daemon and Python 3, plus the libraries in `requirements.txt`. Each experiment folder contains its own README with the exact command; the extended-catalog experiments all use `sh run_experiment.sh`.

## Running the tool

Requirements: Python 3.12 or later (the commit export relies on the
`filter="data"` argument of `tarfile.extractall`), and the libraries in
`requirements.txt`. From the repository root:

```
pip install -r requirements.txt
python main.py <repository> <commit_before> <commit_after> -d <dockerfile>
```

`<repository>` is the path of a local clone, the two commits are SHAs, and
`-d` is the Dockerfile path relative to the repository root. `-o` chooses
the report directory (default `./impact_report`) and `-c` the build context,
which defaults to the directory holding the Dockerfile.

Detection needs nothing but Python. Measurement builds both images, so
stages 3 and 4 need a running Docker daemon; Hadolint and Trivy run as
official containers and need no local installation.

## Test suite

### What you need first

The suite runs in full only where its two external dependencies are present.
Both are optional: every test that needs one is guarded by a `skipif` and
reports a skip rather than a failure when it is missing.

**1. Python 3.12 or later, and the dependencies.**

```
pip install -r requirements.txt
```

**2. A reachable Docker daemon**, for the four end-to-end tests that build
real images and run Hadolint and Trivy against them.

Run the suite **under WSL2 or Linux**, not from Windows. Where Docker Engine
runs inside WSL2 it listens on a Unix socket inside that VM, which the Windows
Python interpreter cannot reach: `docker.from_env()` finds neither `DOCKER_HOST`
nor the Windows named pipe, and those four tests skip.

**3. A local clone of `docker/getting-started`**, for the integration test that
replicates Experiment 3 against a real public history. The test reads two
specific commits, so the clone needs its history — `--depth` will not do.

```
git clone https://github.com/docker/getting-started.git "$HOME/getting-started"
```

> Clone it inside the WSL2 filesystem, not under `/mnt/c`. Git refuses to open
> a repository owned by another user (`detected dubious ownership`), which is
> what a Windows-side clone looks like to WSL2, and the test fails instead of
> skipping.

### Running

```
export GETTING_STARTED_REPO="$HOME/getting-started"
pytest
```

299 tests are collected. With both dependencies present, **all 299 pass and
none is skipped**. Without them the suite still runs and still fails nothing:

| Environment | Result |
|---|---|
| WSL2, Docker running, clone present | 299 passed |
| No `GETTING_STARTED_REPO` | 298 passed, 1 skipped |
| No Docker daemon (e.g. run from Windows) | 295 passed, 4 skipped |
| Neither | 294 passed, 5 skipped |

The 294 that need nothing external cover the detection engine in full, which is
pure Python: a reader wanting only to verify detection needs no Docker and no
network.

### Coverage

```
pytest --cov=src --cov-report=term
```

Measured with the complete suite, this reports **94% over 1285 statements**,
72 uncovered. Measuring without Docker understates it: the end-to-end tests
reach code paths the doubles cannot, and `data_extractor.py` alone falls from
96% to 89%. Quote the figure together with the environment it was measured in.

## License

Released under the MIT License. See LICENSE.
