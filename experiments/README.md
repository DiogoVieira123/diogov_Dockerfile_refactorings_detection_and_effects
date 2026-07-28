# Experiments

Two groups: the five rapid experiments that validate component feasibility, and
the extended catalog of empirical impact measurements.

## Rapid experiments

Table 5.1 of the dissertation. Scripts and raw outputs are kept in each folder.

| # | Folder | Objective | Validated component |
|---|---|---|---|
| Exp 1 | `exp1-poc-refactorings/` | Three-axis measurement principle across four refactorings | Three-metric measurement principle |
| Exp 2 | `exp2-hadolint-trivy-schemas/` | Hadolint and Trivy JSON output schemas as parseable inputs | Data Extractor |
| Exp 3 | `exp3-gitpython-vcs/` | Programmatic Dockerfile retrieval from the Git object model | VCS Connector |
| Exp 4 | `exp4-docker-sdk-size/` | Precise image size retrieval through the Docker daemon API | Performance Analyzer |
| Exp 5 | `exp5-dockerfile-parse-detection/` | Logical-instruction parsing of Dockerfiles | Detection Engine |

Execution: each folder has its own `README.md` with the exact command. Exp 1 runs
`verify_poc.py` inside each `poc-*` subfolder; Exp 2 runs `run.sh`; Exp 3, 4 and 5
run their `teste_*.py` script.

## Extended catalog

`extended_catalog/` holds 15 experiments that measure the impact of the
catalogue's refactoring rules on image size, security and structure, providing
first-hand data for rules the literature does not quantify.

| Folders | Count | Rules | Indicators |
|---|---|---|---|
| `experiment_01_…` – `experiment_15_…` | 15 | R01–R09, R11–R14 (R13 and R14 measured on two dimensions each) | ΔSize, ΔCVEs, ΔWarnings, ΔInstr |

Each folder is self-contained: the two Dockerfile states, the recorded
measurement, the raw tool output, and the execution script. Every experiment is
reproduced with the same command, from inside its folder:

```bash
sh run_experiment.sh
```

All builds use `--no-cache`, and base images are pinned by digest.
See `extended_catalog/README.md` for the experiment table, recorded values,
prerequisites, pinning mechanisms and constraints on reproduction.
