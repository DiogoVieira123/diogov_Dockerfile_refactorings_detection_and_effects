# Experiments

This folder contains two groups of experiments that empirically ground the design and
validation of the prototype.

## Rapid experiments (prototype feasibility)

The five rapid experiments summarised in Table 5.1 of the dissertation. Each one validates
the feasibility of a system component before its inclusion in the design. The supporting
scripts and raw outputs are kept here so that every reported result can be inspected and
reproduced.

| # | Folder | Objective | Validated component |
|---|---|---|---|
| Exp 1 | `exp1-poc-refactorings/` | Validate the three-axis measurement principle across four supported refactorings. | Three-metric measurement principle |
| Exp 2 | `exp2-hadolint-trivy-schemas/` | Validate the Hadolint and Trivy JSON output schemas as parseable inputs. | Data Extractor |
| Exp 3 | `exp3-gitpython-vcs/` | Validate programmatic Dockerfile retrieval from the Git object model. | VCS Connector |
| Exp 4 | `exp4-docker-sdk-size/` | Validate precise image size retrieval through the Docker daemon API. | Performance Analyzer |
| Exp 5 | `exp5-dockerfile-parse-detection/` | Validate logical-instruction parsing of Dockerfiles. | Detection Engine |

## Extended catalog validation

The `extended_catalog/` folder contains four controlled experiments that characterize the
impact of four refactorings of the extended catalog (R06, R09, R11, R12) for which no
empirical measurement is available in the literature. Each experiment compares a Dockerfile
before and after the refactoring on the three quality metrics (image size, Hadolint
warnings, CVEs) to establish its impact profile and confirm the absence of regression. See
`extended_catalog/README.md` for the full description and summary of results.

| Folder | Refactoring |
|---|---|
| `extended_catalog/experiment_1_R06_inline_stage/` | R06 — Inline Stage |
| `extended_catalog/experiment_2_R09_extract_run/` | R09 — Extract RUN Instructions |
| `extended_catalog/experiment_3_R11_move_stage/` | R11 — Move Stage |
| `extended_catalog/experiment_4_R12_remove_run_mv/` | R12 — Remove RUN Instruction (mv command) |
