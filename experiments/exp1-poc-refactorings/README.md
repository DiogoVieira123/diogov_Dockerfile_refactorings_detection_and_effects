# Experiment 1 — Proof-of-Concept Refactorings

## Objective

Validate the three-axis measurement principle by applying four supported
refactorings in isolation and confirming that the three deltas (size, CVEs,
and Hadolint warnings) capture distinct impact profiles. Some refactorings
affect more than one dimension, while others affect only one.

## Method

Each refactoring is applied in isolation to a minimal Dockerfile pair (`before/`
and `after/`). Both images are built, and three metrics are measured for each
side: image size in bytes through the Docker SDK, security vulnerabilities
through Trivy, and structural warnings through Hadolint. The delta for each
metric is the after value minus the before value.

The four refactorings are drawn from the extended catalogue in Table 5.3 of the
dissertation:

| PoC | Refactoring (catalogue ID) | Primary / Secondary | Observed profile |
|---|---|---|---|
| PoC-1 | Inline RUN Instructions (R01) | Performance / Maintainability | Size and DL3059 |
| PoC-2 | Update Base Image TAG (R02) | Security / Performance | DL3007 |
| PoC-3 | Update Base Image (R10) | Security / Performance | Size and CVEs |
| PoC-4 | Replace ADD with COPY (R08) | Security / Maintainability | DL3020 |

## Result

| PoC | Delta Size (bytes) | Delta Warnings | Delta CVEs |
|---|---|---|---|
| PoC-1 Inline RUN Instructions | -187,346 | DL3059 = -3 | 0 |
| PoC-2 Update Base Image TAG | -11,822,119 | DL3007 = -1 | -11 |
| PoC-3 Update Base Image | -26,317,308 | n/a | -25 |
| PoC-4 Replace ADD with COPY | +1 | DL3020 = -1 | 0 |

The refactorings differ in profile. PoC-1 affects performance and maintainability;
PoC-3 affects performance and security simultaneously, with a large reduction in
both image size and vulnerability count when moving to a minimal base image;
PoC-4 affects a single maintainability dimension through the DL3020 warning, with
no measurable size or security impact. This confirms that the three deltas
correctly distinguish the impact profile of each refactoring type, supporting the
primary and secondary classification of the extended catalogue.

## Validated component

The three-metric measurement principle.

## How to reproduce

Requirements: a running Docker daemon and the Python Docker SDK
(`pip3 install docker`). Hadolint and Trivy run as containers, so no local
installation is needed.

    chmod +x run_one.sh
    ./run_one.sh poc-1-inline-run
    ./run_one.sh poc-2-update-base-image-tag
    ./run_one.sh poc-3-update-base-image
    ./run_one.sh poc-4-replace-add-with-copy
    python3 extract_deltas.py

Each run produces, inside the corresponding PoC folder, the Hadolint JSON
outputs, the Trivy JSON outputs, and the image sizes. The `extract_deltas.py`
script then computes the three deltas and writes a `deltas.md` file in each
folder.

Note on PoC-2: the `before` image uses the mutable `ubuntu:latest` tag, which
resolved to Ubuntu 26.04 at measurement time (recorded in
`poc-2-update-base-image-tag/latest-resolved-digest.txt`). Re-running on a later
date may yield different size and CVE values, but the elimination of the DL3007
smell is stable. Only the DL3007 warning delta is part of the argument for this
PoC; its size and CVE deltas are not.
