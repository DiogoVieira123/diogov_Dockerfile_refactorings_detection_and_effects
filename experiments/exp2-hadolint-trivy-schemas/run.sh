#!/bin/sh
# Experiment 2 — reproduces the two commands documented in README.md, unchanged.
# Usage: ./run.sh [path-to-Dockerfile]
#
# Dependency: trivy-output.json was generated against the poc-1-inline-run:before
# image from Experiment 1, so that image must be built first:
#     ../exp1-poc-refactorings/run_one.sh poc-1-inline-run
set -u

DOCKERFILE="${1:-Dockerfile}"

# Hadolint, against a Dockerfile (JSON schema under test, findings irrelevant):
docker run --rm -i hadolint/hadolint hadolint --format json - < "$DOCKERFILE" > hadolint-output.json

# Trivy, against the built PoC-1 before image:
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy image --format json poc-1-inline-run:before > trivy-output.json
