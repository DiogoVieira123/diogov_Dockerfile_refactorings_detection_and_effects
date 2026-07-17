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

## Result

| PoC | Delta Size (bytes) | Delta Warnings | Delta CVEs | Delta Instr |
|---|---|---|---|---|
| R01 Inline RUN Instructions | -194,991 | +0 | +0 | -3 |
| R02 Update Base Image TAG | -11,845,577 | -1 | -26 | +0 |
| R10 Update Base Image | -26,318,550 | +0 | -15 | +0 |
| R08 Replace ADD with COPY | +3 | -1 | +0 | +0 |

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

Requirements: a running Docker daemon and Python 3 with `dockerfile-parse`
(`pip install dockerfile-parse`). Hadolint and Trivy run as containers, so no
local installation is needed.

Each PoC folder carries a standalone `verify_poc.py`. Open a terminal in this
directory and run one per PoC:

    (cd poc-1-inline-run            && python verify_poc.py)
    (cd poc-2-update-base-image-tag && python verify_poc.py)
    (cd poc-3-update-base-image     && python verify_poc.py)
    (cd poc-4-replace-add-with-copy && python verify_poc.py)

For each PoC the script rebuilds the `before/` and `after/` images with
`--no-cache`, re-measures the four indicators (image size via the Docker SDK,
Trivy CVEs, Hadolint warnings, logical instruction count), computes the Delta
for each, and compares every Delta against the value reported above, printing
`OK` or `DIFF` per line. If Docker requires elevated privileges, prefix the
command with `sudo`.

Note on PoC-2: the `before` image uses the mutable `ubuntu:latest` tag, which
resolved to Ubuntu 26.04 at measurement time (recorded in
`poc-2-update-base-image-tag/latest-resolved-digest.txt`). Re-running on a later
date may yield different size and CVE values, but the elimination of the DL3007
smell is stable. Only the DL3007 warning delta is part of the argument for this
PoC; its size and CVE deltas are not.

Note on base-image digests: PoC-1, PoC-3, and PoC-4 use fixed tags
(`ubuntu:22.04`, `alpine:3.19`). For reproducibility, the SHA256 digest to which
each pinned tag resolves is recorded in a `base-image-digest.txt` file inside
the corresponding PoC folder (obtained via
`docker inspect --format='{{index .RepoDigests 0}}' <image>`). The Dockerfiles
themselves are unchanged and keep their tags.
