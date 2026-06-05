# Experiment 5 — Dockerfile Parsing and Refactoring Detection

## Objective

Confirm that two Dockerfiles can be parsed into their logical instructions and
that a refactoring can be detected automatically by comparing them. In this case,
the goal is to detect a RUN consolidation (several RUN instructions merged into
one) between a before and an after version. This is the capability the Detection
Engine relies on to identify refactorings.

## Method

The dockerfile-parse library parses each Dockerfile into a structured list of
instructions. The RUN instructions are counted in both the before and the after
version. A simple detection rule then compares the two counts: if the before
version has more RUN instructions than the after version, a RUN consolidation is
reported.

## Result

The before Dockerfile contained 4 RUN instructions and the after Dockerfile
contained 1. The detection rule correctly reported a RUN consolidation
(4 to 1). This confirms that logical-instruction parsing is sufficient to detect
a structural refactoring automatically. The captured output is in `output.txt`.

## Validated component

Detection Engine — parsing of Dockerfile instructions and automatic detection of
a refactoring from the structural difference between two versions.

## How to reproduce

Requirements: Python with dockerfile-parse installed
(`pip install dockerfile-parse`).

    python3 teste_dockerfile_parse.py

The script reads `Dockerfile-antes` and `Dockerfile-depois`, counts the RUN
instructions in each, and reports whether a RUN consolidation was detected, as
captured in `output.txt`. The script must be run from inside this folder, since
it opens the Dockerfiles by relative path.
