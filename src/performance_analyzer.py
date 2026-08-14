"""Performance Analyzer — image size measurement (Chapter 5, Section 5.5).

Stage 3 measurement component, running in parallel with the Data Extractor. It
receives the references to the two images Stage 3's preparation built (see
``image_builder``) and returns the signed size delta between them (RF4).

The component measures and nothing else. It does not build, and it never
reads a value produced by the Data Extractor: ΔSize is computed from the two
images alone, just as ΔCVEs, ΔWarnings and ΔInstr are computed without ΔSize.
That mutual independence is what allows the two measurement components to run
concurrently, and this module holds no state and shares no object with either
the preparation or its sibling — only the image references, which both
consume read-only.

Size is read from ``image.attrs["Size"]`` through the Docker SDK, never from
the Docker CLI. The CLI applies decimal rounding and human-readable truncation
by design (Docker issue #31298), which would collapse the micro-variations the
catalogue produces — the +417 bytes measured for R09, for instance — to zero
and violate RNF1. The SDK attribute returns the VirtualSize, the total
uncompressed byte count of all image layers, as a 64-bit integer; Experiment 4
confirmed it reports 29,748,045 bytes exactly for ubuntu:22.04.

Build time was considered as a second performance metric and excluded: it is
too sensitive to host hardware, cache state and network latency for a single
measurement per state to be meaningful, whereas image size is a deterministic
function of the Dockerfile content and the base image state.

All Docker SDK failures — daemon unavailable, image missing, inspection
failure — surface as :class:`PerformanceAnalyzerError` (RNF4), so the pipeline
can distinguish a measurement failure from a defect of its own.
"""

from __future__ import annotations

import contextlib
from typing import NamedTuple

import docker
from docker.errors import APIError, DockerException, ImageNotFound


class PerformanceAnalyzerError(Exception):
    """Image size could not be measured for one of the Dockerfile states.

    RNF4: every Docker SDK failure — an unreachable daemon, an image the
    daemon does not know, metadata that carries no usable size — is re-raised
    as this exception with the underlying cause attached, so the pipeline can
    tell a measurement failure from a build failure upstream
    (``ImageBuildError``) or a bug in its own logic.
    """


class SizeMetric(NamedTuple):
    """Image size of both Dockerfile states and the delta between them.

    RF4 expresses the delta exclusively in bytes, the same absolute-value form
    the other three pipeline metrics use, so the four deltas the Report
    Generator aggregates share one unit convention. The sign convention is the
    one used throughout the study: ``size_after`` minus ``size_before``, so a
    negative delta is a size reduction.
    """

    size_before: int  # bytes, image.attrs["Size"] of the before state
    size_after: int  # bytes, image.attrs["Size"] of the after state
    delta_size: int  # signed byte difference; negative means the image shrank

    @classmethod
    def from_sizes(cls, size_before: int, size_after: int) -> "SizeMetric":
        """Build the metric from the two measured sizes, deriving the delta."""
        return cls(
            size_before=size_before,
            size_after=size_after,
            delta_size=size_after - size_before,
        )


def _connect() -> docker.DockerClient:
    """Open a client against the local Docker daemon.

    The component opens its own connection rather than receiving one, so it
    shares no mutable object with the Data Extractor running alongside it.

    Raises:
        PerformanceAnalyzerError: the daemon is not running or not reachable
            through the environment's Docker configuration (RNF4).
    """
    try:
        return docker.from_env()
    except DockerException as exc:
        raise PerformanceAnalyzerError(
            f"Could not connect to the Docker daemon: {exc}"
        ) from exc


def _image_size(client: docker.DockerClient, image_reference: str, label: str) -> int:
    """Read the exact uncompressed byte size of one built image.

    ``image.attrs["Size"]`` is the VirtualSize reported by the daemon API as a
    64-bit integer, the byte-level resolution RNF1 requires.

    Args:
        client: an open Docker client.
        image_reference: ID or tag of an image the preparation built.
        label: which state is being measured ("before"/"after"), used only to
            make the diagnostic message identify the failing side.

    Raises:
        PerformanceAnalyzerError: the image is unknown to the daemon or its
            metadata carries no usable size (RNF4).
    """
    try:
        image = client.images.get(image_reference)
    except ImageNotFound as exc:
        raise PerformanceAnalyzerError(
            f"The '{label}' image is not known to the Docker daemon: "
            f"{image_reference}"
        ) from exc
    except (APIError, DockerException) as exc:
        raise PerformanceAnalyzerError(
            f"Docker daemon error while inspecting the '{label}' image: {exc}"
        ) from exc

    try:
        size = image.attrs["Size"]
    except (KeyError, TypeError, AttributeError) as exc:
        raise PerformanceAnalyzerError(
            f"Could not inspect the size of the '{label}' image: the daemon "
            f"returned no usable Size attribute ({exc})."
        ) from exc
    if not isinstance(size, int):
        raise PerformanceAnalyzerError(
            f"Could not inspect the size of the '{label}' image: expected an "
            f"integer byte count, got {type(size).__name__}."
        )
    return size


def measure_size_delta(image_before: str, image_after: str) -> SizeMetric:
    """Measure the size of both built images and the delta between them (RF4).

    The component's entry point. Both images must already exist; building them
    is the preparation's responsibility (``image_builder``), and their
    removal is too, so this function leaves the daemon exactly as it found it.

    Args:
        image_before: ID or tag of the image built from the earlier state.
        image_after: ID or tag of the image built from the later state.

    Returns:
        The sizes of both states and the signed delta between them, all in
        bytes.

    Raises:
        PerformanceAnalyzerError: the daemon is unreachable, either image is
            unknown, or a size cannot be inspected (RNF4).
    """
    client = _connect()
    try:
        return SizeMetric.from_sizes(
            _image_size(client, image_before, "before"),
            _image_size(client, image_after, "after"),
        )
    finally:
        with contextlib.suppress(Exception):
            client.close()
