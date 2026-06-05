# Experiment 2 — Hadolint and Trivy JSON Schemas

## Objective

Validate that Hadolint and Trivy can both emit machine-readable JSON output, and
that the structure of that output is stable and parseable, so that the Data
Extractor can consume both tools programmatically. The specific findings of each
tool are not relevant here; only the output format is under test.

## Method

Both tools were run in JSON output mode and their output structure was inspected.

Hadolint, against a Dockerfile:

    docker run --rm -i hadolint/hadolint hadolint --format json - < Dockerfile

Trivy, against a built image:

    docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy image --format json poc-1-inline-run:before > trivy-output.json

## Result

Both tools produced well-formed JSON. Hadolint returns a flat array of objects,
each with the fields `code`, `column`, `file`, `level`, `line`, and `message`.
Trivy returns a nested structure, with a top-level `Results` array whose entries
contain a `Vulnerabilities` array, each carrying a `VulnerabilityID` and a
`Severity` field. Both formats are stable and directly parseable, which is the
requirement the Data Extractor depends on. The captured outputs are in
`hadolint-output.json` and `trivy-output.json`.

## Validated component

Data Extractor — confirmation that Hadolint and Trivy expose parseable JSON
output for programmatic consumption.

## How to reproduce

Run the two commands above and inspect the resulting files to confirm that both
produce well-formed, parseable JSON with the field structure described above.
