# Case Study: Rule R05 (Extract Stage)

This repository contains the documentation and experimental artifacts used to validate the refactoring rule **R05 — Extract Stage (Multi-stage build)**.

## 1. Motivation
Rule R05 was selected as a representative case study to validate the impact of Dockerfile refactoring on container image security. While the complete rule catalog covers 14 distinct rules focused on different dimensions (Performance, Maintainability, Security), R05 was prioritized for empirical validation due to its significant potential to minimize the image's attack surface by excluding build-time dependencies from the final runtime image.

## 2. Reproduction
To reproduce these results, ensure you have `Docker` and `Trivy` installed, then execute the provided script:

```bash
chmod +x run_experiment.sh
./run_experiment.sh