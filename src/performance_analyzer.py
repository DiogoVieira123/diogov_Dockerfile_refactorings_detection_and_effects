"""Performance Analyzer — image size measurement (Chapter 5, Section 5.5).

Third component of the pipeline, running in parallel with the Data Extractor.
It receives the two Dockerfile states delivered by the VCS Connector, builds
the Docker image for each, and returns the signed size delta between them
(RF4).

Size is read from ``image.attrs["Size"]`` through the Docker SDK, never from
the Docker CLI. The CLI applies decimal rounding and human-readable truncation
by design (Docker issue #31298), which would collapse the micro-variations the
catalogue produces — the +417 bytes measured for R09, for instance — to zero
and violate RNF1. The SDK attribute returns the VirtualSize, the total
uncompressed byte count of all image layers, as a 64-bit integer; Experiment 4
confirmed it reports 29,748,045 bytes exactly for ubuntu:22.04.

Two properties govern the implementation:

* **Nothing is written to the working directory.** The build context is
  assembled as a tar archive in memory and handed to the daemon as a byte
  stream, so analysing a repository never leaves temporary Dockerfiles or
  context copies behind on the caller's disk.
* **No image outlives the measurement.** Every image the component builds is
  removed before it returns, including when the second build fails after the
  first succeeded. Left unchecked, a catalogue-wide run would accumulate
  dozens of images and exhaust the daemon's storage.

Build time was considered as a second performance metric and excluded: it is
too sensitive to host hardware, cache state and network latency for a single
measurement per state to be meaningful, whereas image size is a deterministic
function of the Dockerfile content and the base image state.

All Docker SDK failures — daemon unavailable, build error, inspection failure
— surface as :class:`PerformanceAnalyzerError` (RNF4), so the pipeline can
distinguish an analysis failure from a defect of its own.
"""

from __future__ import annotations

import contextlib
import io
import tarfile
import uuid
from pathlib import Path
from typing import Iterator, List, NamedTuple, Optional, Tuple, Union

import docker
from docker.errors import APIError, BuildError, DockerException, ImageNotFound
from docker.models.images import Image


class PerformanceAnalyzerError(Exception):
    """Image size could not be measured for one of the Dockerfile states.

    RNF4: every Docker SDK failure — an unreachable daemon, a build that does
    not complete, an image whose metadata cannot be inspected — is re-raised
    as this exception with the underlying cause attached, so the pipeline can
    tell an analysis failure from a bug in its own logic and abort cleanly
    with an informative diagnostic.
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


# Path the injected Dockerfile takes inside the in-memory build context.
_DOCKERFILE_ARCNAME = "Dockerfile"

# Tag prefix for the throwaway images; Docker rejects upper case in tags, so
# the prefix stays lower case and the suffix is a hex UUID.
_TAG_PREFIX = "dockerfile-refactoring-analysis"

# Directories that never belong in a build context sent to the daemon.
_EXCLUDED_CONTEXT_DIRS = frozenset({".git", "__pycache__", ".venv", "node_modules"})


def _connect() -> docker.DockerClient:
    """Open a client against the local Docker daemon.

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


def _context_archive(
    dockerfile_content: str, context_path: Optional[Path]
) -> io.BytesIO:
    """Assemble the build context as an in-memory tar stream.

    The Dockerfile is injected into the archive rather than read from disk, so
    the content delivered by the VCS Connector is built exactly as it was
    committed and no file is written to the working directory. When
    ``context_path`` is given its files travel with it, which is what allows
    Dockerfiles carrying COPY instructions to build; without one the context
    holds the Dockerfile alone.

    Any file already named ``Dockerfile`` at the root of the context is
    skipped, since the injected content is the state under analysis.
    """
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        if context_path is not None:
            for entry in sorted(context_path.rglob("*")):
                if not entry.is_file():
                    continue
                relative = entry.relative_to(context_path)
                if _EXCLUDED_CONTEXT_DIRS.intersection(relative.parts):
                    continue
                arcname = relative.as_posix()
                if arcname == _DOCKERFILE_ARCNAME:
                    continue  # superseded by the state under analysis
                archive.add(entry, arcname=arcname)

        payload = dockerfile_content.encode("utf-8")
        info = tarfile.TarInfo(name=_DOCKERFILE_ARCNAME)
        info.size = len(payload)
        info.mtime = 0  # fixed timestamp: the archive is a deterministic input
        archive.addfile(info, io.BytesIO(payload))

    stream.seek(0)
    return stream


def _build_image(
    client: docker.DockerClient,
    dockerfile_content: str,
    context_path: Optional[Path],
    label: str,
) -> Image:
    """Build one Dockerfile state and return the resulting image.

    Args:
        client: an open Docker client.
        dockerfile_content: the Dockerfile text for this state.
        context_path: directory whose files accompany the build, or None.
        label: which state is being built ("before"/"after"), used only to
            make the diagnostic message identify the failing side.

    Raises:
        PerformanceAnalyzerError: the build did not complete (RNF4).
    """
    tag = f"{_TAG_PREFIX}:{uuid.uuid4().hex}"
    try:
        image, _logs = client.images.build(
            fileobj=_context_archive(dockerfile_content, context_path),
            custom_context=True,
            dockerfile=_DOCKERFILE_ARCNAME,
            tag=tag,
            rm=True,  # discard intermediate containers
            forcerm=True,  # discard them even when the build fails
            pull=False,  # a cached base image keeps the two states comparable
        )
    except BuildError as exc:
        raise PerformanceAnalyzerError(
            f"Docker build of the '{label}' Dockerfile state failed: {exc}"
        ) from exc
    except (APIError, DockerException) as exc:
        raise PerformanceAnalyzerError(
            f"Docker daemon error while building the '{label}' Dockerfile "
            f"state: {exc}"
        ) from exc
    return image


def _image_size(image: Image, label: str) -> int:
    """Read the exact uncompressed byte size of a built image.

    ``image.attrs["Size"]`` is the VirtualSize reported by the daemon API as a
    64-bit integer, the byte-level resolution RNF1 requires.

    Raises:
        PerformanceAnalyzerError: the image metadata does not carry a usable
            size (RNF4).
    """
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


def _remove_images(client: docker.DockerClient, images: List[Image]) -> None:
    """Remove every image the analysis built.

    Runs during cleanup, where an exception would mask the failure that
    triggered it, so removal errors are swallowed deliberately: an image that
    is already gone, or that the daemon refuses to delete, must not replace
    the original diagnostic. Each image is attempted independently so one
    failure does not leave the others behind.
    """
    for image in images:
        with contextlib.suppress(ImageNotFound, APIError, DockerException):
            client.images.remove(image.id, force=True)


@contextlib.contextmanager
def measured_image_pair(
    dockerfile_before: str,
    dockerfile_after: str,
    context_path: Optional[Union[str, Path]] = None,
) -> Iterator[Tuple[SizeMetric, str, str]]:
    """Build both states, yield their size metric and image IDs, then clean up.

    This is the component's primitive operation. It exists alongside
    :func:`measure_size_delta` because the Data Extractor scans the built
    images with Trivy (design chapter, Table 4.9, step 3b): running inside this
    context lets that component reach the same images instead of rebuilding
    them, while the images still cannot outlive the analysis.

    Both images are removed on exit whatever happens — a failed second build,
    an exception raised by the caller inside the block, or an ordinary return.

    Args:
        dockerfile_before: Dockerfile content at the earlier commit.
        dockerfile_after: Dockerfile content at the later commit.
        context_path: directory whose files accompany both builds, required
            when the Dockerfiles carry COPY or ADD instructions reading from
            the build context. Defaults to None, a context holding only the
            Dockerfile.

    Yields:
        The :class:`SizeMetric` and the IDs of the before and after images.

    Raises:
        PerformanceAnalyzerError: the daemon is unreachable, either build
            fails, or an image size cannot be inspected (RNF4).
    """
    resolved_context = Path(context_path) if context_path is not None else None
    if resolved_context is not None and not resolved_context.is_dir():
        raise PerformanceAnalyzerError(
            f"Build context path is not a directory: {resolved_context}"
        )

    client = _connect()
    built: List[Image] = []
    try:
        image_before = _build_image(
            client, dockerfile_before, resolved_context, "before"
        )
        built.append(image_before)
        image_after = _build_image(client, dockerfile_after, resolved_context, "after")
        built.append(image_after)

        metric = SizeMetric.from_sizes(
            _image_size(image_before, "before"), _image_size(image_after, "after")
        )
        yield metric, image_before.id, image_after.id
    finally:
        _remove_images(client, built)
        with contextlib.suppress(Exception):
            client.close()


def measure_size_delta(
    dockerfile_before: str,
    dockerfile_after: str,
    context_path: Optional[Union[str, Path]] = None,
) -> SizeMetric:
    """Measure the image size of both Dockerfile states and their delta (RF4).

    The component's main entry point. Both images are built, measured and
    removed before the call returns.

    Args:
        dockerfile_before: Dockerfile content at the earlier commit.
        dockerfile_after: Dockerfile content at the later commit.
        context_path: directory whose files accompany both builds, required
            when the Dockerfiles carry COPY or ADD instructions reading from
            the build context.

    Returns:
        The sizes of both states and the signed delta between them, all in
        bytes.

    Raises:
        PerformanceAnalyzerError: the daemon is unreachable, either build
            fails, or an image size cannot be inspected (RNF4).
    """
    with measured_image_pair(
        dockerfile_before, dockerfile_after, context_path
    ) as (metric, _id_before, _id_after):
        return metric


def docker_engine_version() -> str:
    """Version string of the Docker Engine the measurements ran against.

    Exposed for the Report Generator, which records the version of every
    external tool invoked (RNF5). The version is only reachable through a
    Docker client, and this component is the one that owns that connection.

    Raises:
        PerformanceAnalyzerError: the daemon is unreachable or does not report
            a version (RNF4).
    """
    client = _connect()
    try:
        return str(client.version()["Version"])
    except (KeyError, TypeError, APIError, DockerException) as exc:
        raise PerformanceAnalyzerError(
            f"Could not read the Docker Engine version: {exc}"
        ) from exc
    finally:
        with contextlib.suppress(Exception):
            client.close()
