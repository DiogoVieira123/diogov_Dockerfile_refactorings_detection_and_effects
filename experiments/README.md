# Experiments

This folder contains the five rapid experiments that empirically ground the design
of the prototype, as summarised in Table 5.1 of the dissertation. Each experiment
validates the feasibility of a system component before its inclusion in the design.
The supporting scripts and raw outputs are kept here so that every reported result
can be inspected and reproduced.

| # | Folder | Objective | Validated component |
|---|---|---|---|
| Exp 1 | `exp1-poc-refactorings/` | Validate the three-axis measurement principle across four supported refactorings. | Three-metric measurement principle |
| Exp 2 | `exp2-hadolint-trivy-schemas/` | Validate the Hadolint and Trivy JSON output schemas as parseable inputs. | Data Extractor |
| Exp 3 | `exp3-gitpython-vcs/` | Validate programmatic Dockerfile retrieval from the Git object model. | VCS Connector |
| Exp 4 | `exp4-docker-sdk-size/` | Validate precise image size retrieval through the Docker daemon API. | Performance Analyzer |
| Exp 5 | `exp5-dockerfile-parse-detection/` | Validate logical-instruction parsing of Dockerfiles. | Detection Engine |
