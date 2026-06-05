# Dockerfile Refactorings: Detection and Effects

Supporting repository for the MSc dissertation **"Dockerfile Refactorings:
Detection and Effects"**, developed at the Instituto Superior de Engenharia do
Porto (ISEP).

- **Author:** Diogo Pereira Vieira
- **Supervisor:** Prof. Isabel Azevedo
- **Programme:** MSc in Computer Engineering, specialization in Cybersecurity and Systems Administration

## About

The dissertation proposes an extended catalogue of Dockerfile refactorings
classified by quality dimension (performance, security, maintainability), and a
Python prototype that automatically detects refactorings between two versions of
a Dockerfile and measures their impact across three metrics: image size,
vulnerability count (CVEs), and linter warnings.

This repository holds the empirical material that supports the design described
in Chapter 5: five rapid experiments, each validating the technical feasibility
of one element of the prototype before its design was finalised.

## Structure

- `experiments/` — five rapid experiments grounding the prototype design (see Table 5.1 of the dissertation). Each subfolder contains the scripts, raw tool outputs, and a README describing the objective, method, result, and validated component.
- `prototype/` — prototype implementation (Chapter 6). Not yet included; to be added once the implementation phase is complete.

## Experiments

| # | Folder | Validated component |
|---|---|---|
| Exp 1 | `experiments/exp1-poc-refactorings/` | Three-metric measurement principle (four proof-of-concept refactorings) |
| Exp 2 | `experiments/exp2-hadolint-trivy-schemas/` | Data Extractor (Hadolint and Trivy JSON schemas) |
| Exp 3 | `experiments/exp3-gitpython-vcs/` | VCS Connector (GitPython) |
| Exp 4 | `experiments/exp4-docker-sdk-size/` | Performance Analyzer (Docker SDK) |
| Exp 5 | `experiments/exp5-dockerfile-parse-detection/` | Detection Engine (dockerfile-parse) |

## Tools used

- [Hadolint](https://github.com/hadolint/hadolint) — Dockerfile linter (warnings)
- [Trivy](https://github.com/aquasecurity/trivy) — vulnerability scanner (CVEs)
- [Docker SDK for Python](https://docker-py.readthedocs.io/) — image size
- [GitPython](https://gitpython.readthedocs.io/) — Git history access
- [dockerfile-parse](https://github.com/containerbuildsystem/dockerfile-parse) — Dockerfile parsing

## Reproducing the experiments

Each experiment folder contains its own `README.md` with the exact commands. In
general, the experiments require a running Docker daemon and Python 3, with the
tool-specific libraries noted in each folder. Experiments 2 and 4 use the Docker
daemon; Hadolint and Trivy run as containers, so no local installation of those
two is needed.

## License

Released under the MIT License. See `LICENSE`.
