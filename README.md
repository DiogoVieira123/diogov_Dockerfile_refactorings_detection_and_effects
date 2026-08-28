# Dockerfile Refactorings: Detection and Effects

Supporting repository for the MSc dissertation "Dockerfile Refactorings: Detection and Effects", developed at the Instituto Superior de Engenharia do Porto (ISEP).

**Author:** Diogo Pereira Vieira
**Supervisor:** Prof. Isabel Azevedo
**Programme:** MSc in Computer Engineering, specialization in Cybersecurity and Systems Administration

## About

The dissertation proposes an extended catalogue of Dockerfile refactorings classified by quality dimension (performance, security, maintainability), and a Python prototype that automatically detects refactorings between two versions of a Dockerfile and measures their impact across three metrics: image size, vulnerability count (CVEs), and linter warnings.

This repository holds the empirical material that supports the design described in Chapter 5, and the literature review replication package.

## Structure

| Path | Content |
|---|---|
| `experiments/` | empirical material supporting Chapter 5 |
| `experiments/extended_catalog/` | 15 experiments measuring the impact of the catalogue's rules |
| `literature-review/` | PRISMA replication package: raw database exports, screening scripts and logs |
| `DESIGN_CHAPTER.md` | Chapter 5 — design of the prototype |
| `PROJECT_CONTEXT.md` | architecture and technology constraints |
| `requirements.txt` | Python dependencies |

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

## License

Released under the MIT License. See LICENSE.
