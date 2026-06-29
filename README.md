# Dockerfile Refactorings: Detection and Effects

Supporting repository for the MSc dissertation "Dockerfile Refactorings: Detection and Effects", developed at the Instituto Superior de Engenharia do Porto (ISEP).

**Author:** Diogo Pereira Vieira
**Supervisor:** Prof. Isabel Azevedo
**Programme:** MSc in Computer Engineering, specialization in Cybersecurity and Systems Administration

## About

The dissertation proposes an extended catalogue of Dockerfile refactorings classified by quality dimension (performance, security, maintainability), and a Python prototype that automatically detects refactorings between two versions of a Dockerfile and measures their impact across three metrics: image size, vulnerability count (CVEs), and linter warnings.

This repository holds the empirical material that supports the design described in Chapter 5: five rapid experiments that validate the technical feasibility of the prototype components, and four extended-catalog experiments that characterize the impact of refactorings for which no empirical measurement exists in the literature.

## Structure

`experiments/` — empirical material supporting Chapter 5, organized in two groups:
- **Rapid experiments** (Table 5.1): five experiments, each validating the technical feasibility of one element of the prototype before its design was finalised.
- **Extended catalog validation** (`experiments/extended_catalog/`): four controlled experiments measuring the impact of refactorings R06, R09, R11, and R12 on the three quality metrics.

Each subfolder contains the scripts, raw tool outputs, and a README describing the objective, method, result, and (for the rapid experiments) the validated component.

`prototype/` — prototype implementation (Chapter 6). Not yet included; to be added once the implementation phase is complete.

## Rapid experiments

| # | Folder | Validated component |
|---|---|---|
| Exp 1 | `experiments/exp1-poc-refactorings/` | Three-metric measurement principle (four proof-of-concept refactorings) |
| Exp 2 | `experiments/exp2-hadolint-trivy-schemas/` | Data Extractor (Hadolint and Trivy JSON schemas) |
| Exp 3 | `experiments/exp3-gitpython-vcs/` | VCS Connector (GitPython) |
| Exp 4 | `experiments/exp4-docker-sdk-size/` | Performance Analyzer (Docker SDK) |
| Exp 5 | `experiments/exp5-dockerfile-parse-detection/` | Detection Engine (dockerfile-parse) |

## Extended catalog validation

| Folder | Refactoring |
|---|---|
| `experiments/extended_catalog/experiment_1_R06_inline_stage/` | R06 — Inline Stage |
| `experiments/extended_catalog/experiment_2_R09_extract_run/` | R09 — Extract RUN Instructions |
| `experiments/extended_catalog/experiment_3_R11_move_stage/` | R11 — Move Stage |
| `experiments/extended_catalog/experiment_4_R12_remove_run_mv/` | R12 — Remove RUN Instruction (mv command) |

## Tools used

- **Hadolint** — Dockerfile linter (warnings)
- **Trivy** — vulnerability scanner (CVEs)
- **Docker SDK for Python** — image size
- **GitPython** — Git history access
- **dockerfile-parse** — Dockerfile parsing

## Reproducing the experiments

Each experiment folder contains its own README.md with the exact commands. In general, the experiments require a running Docker daemon and Python 3, with the tool-specific libraries noted in each folder. Hadolint and Trivy run as containers, so no local installation of those two is needed. The extended-catalog experiments are run with the `measure.sh` script in each folder.

## License

Released under the MIT License. See LICENSE.