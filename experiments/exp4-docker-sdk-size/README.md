# Experiment 4 — Image Size Retrieval with the Docker SDK

## Objective

Confirm that the exact size of a Docker image can be obtained in bytes directly
through Python, using the Docker SDK, without parsing the visual output of
`docker images`. This is the capability the Performance Analyzer relies on to
compute the size delta between two image states.

## Method

The Docker SDK connects to the local Docker daemon. A locally built image is
referenced by name, and its size in bytes is read from the image attributes
(`image.attrs["Size"]`). The byte value is then converted to MB for display.

## Result

The SDK returned a size of 189,410,351 bytes (180.64 MB) for the test image. The
value is obtained as an integer number of bytes directly from the Docker API,
which is the precision the Performance Analyzer requires; reading the rounded
text output of `docker images` would lose that precision. The captured output is
in `output.txt`.

## Validated component

Performance Analyzer — exact image size retrieval in bytes through the Docker
daemon API.

## How to reproduce

Requirements: a running Docker daemon, the Python Docker SDK
(`pip install docker`), and a locally built image.

    python3 teste_docker_sdk.py

The script prints the image size in bytes and in MB, as captured in `output.txt`.
Adjust the image name in the script (`poc:baseline`) to match an image present
in your local Docker environment.
