# Experiment 4 — Image Size Retrieval with the Docker SDK

## Objective

Confirm that the exact size of a Docker image can be obtained in bytes directly
through Python, using the Docker SDK, without parsing the visual output of
`docker images`. This is the capability the Performance Analyzer relies on to
compute the size delta between two image states.

## Method

The Docker SDK connects to the local Docker daemon. The public, documented test
image `ubuntu:22.04` is pulled and referenced by name, and its size in bytes is
read from the image attributes (`image.attrs["Size"]`). The byte value is then
converted to MB for display.

## Result

The SDK returned a size of 29,748,045 bytes (28.37 MB) for the `ubuntu:22.04`
test image. The value is obtained as an integer number of bytes directly from
the Docker API, which is the precision the Performance Analyzer requires;
reading the rounded text output of `docker images` would lose that precision.
The captured output is in `output.txt`. The exact image measured is pinned by
its SHA256 digest, recorded in `base-image-digest.txt` for reproducibility;
re-running after the `ubuntu:22.04` tag is re-published may yield a slightly
different byte count, but the digest identifies the image this measurement
refers to.

## Validated component

Performance Analyzer — exact image size retrieval in bytes through the Docker
daemon API.

## How to reproduce

Requirements: a running Docker daemon and the Python Docker SDK
(`pip install docker`). The script pulls `ubuntu:22.04` automatically.

    python3 teste_docker_sdk.py

The script prints the image size in bytes and in MB, as captured in
`output.txt`.
