"""Stage 3, preparation — builds the images the measurement consumes.

Stage 3 measures with the Performance Analyzer and the Data Extractor running
in parallel, and neither may depend on the other. Both nonetheless need the
same resource: the Performance Analyzer reads the size of each built image,
and the Data Extractor scans those images with Trivy. Leaving the build inside
either component would make the other wait on it, so the build is lifted out
into this preparation step, owned by the pipeline orchestrator and completed
before the measurement begins.

The two components then consume the resulting image references independently
and concurrently, which is what makes their parallel execution genuine rather
than nominal, and what keeps the most expensive operation of the pipeline —
building the images — from happening twice.

Three properties govern the implementation:

* **The build runs on BuildKit.** ``docker buildx build --load`` is invoked as
  a subprocess, because the Docker SDK for Python speaks only to the classic
  ``/build`` endpoint and has no BuildKit option. The classic builder rejects
  the modern Dockerfile syntax — ``COPY --chmod``, ``RUN --mount``, heredocs —
  which real Dockerfiles use. ``--load`` places the result in the daemon's
  image store, so the size measurement still reads ``attrs["Size"]`` through
  the SDK and byte precision is untouched (RNF1).
* **The caller's files are never written to.** The Dockerfile under analysis is
  staged in a temporary directory of its own and passed with ``--file``, so the
  exported commit tree serving as the build context is left exactly as Git
  wrote it.
* **No image outlives the analysis.** Both images are removed when the
  preparation context closes, whatever happens inside it. Left unchecked, a
  catalogue-wide run would accumulate dozens of images and exhaust the
  daemon's storage.

Every failure — an unreachable daemon, an absent buildx, a build that does not
complete, a build that overruns its timeout — surfaces as
:class:`ImageBuildError` (RNF4), so the pipeline can distinguish a preparation
failure from a defect of its own or from a measurement failure downstream.
"""

from __future__ import annotations

import contextlib
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Iterator, List, NamedTuple, Optional, Union

import docker
from docker.errors import APIError, DockerException, ImageNotFound
from docker.models.images import Image


class ImageBuildError(Exception):
    """An image could not be built for one of the Dockerfile states.

    RNF4: every Docker SDK failure during preparation — an unreachable daemon,
    a build that does not complete — is re-raised as this exception with the
    underlying cause attached, so the pipeline can abort cleanly before the measurement
    starts and report which state failed.
    """


class BuiltImagePair(NamedTuple):
    """References to the images built for the two Dockerfile states.

    Identifiers rather than SDK objects, so the measurement components consume the
    resource without sharing a client, a connection or any object graph with
    the preparation or with each other.
    """

    image_before: str  # image ID of the earlier commit's state
    image_after: str  # image ID of the later commit's state


# Name the staged Dockerfile takes in its temporary directory.
_DOCKERFILE_ARCNAME = "Dockerfile"

# Tag prefix for the throwaway images; Docker rejects upper case in tags, so
# the prefix stays lower case and the suffix is a hex UUID.
_TAG_PREFIX = "dockerfile-refactoring-analysis"

# A hung build must not stall a batch of analyses indefinitely.
_BUILD_TIMEOUT_SECONDS = 1800


def _connect() -> docker.DockerClient:
    """Open a client against the local Docker daemon.

    Raises:
        ImageBuildError: the daemon is not running or not reachable through
            the environment's Docker configuration (RNF4).
    """
    try:
        return docker.from_env()
    except DockerException as exc:
        raise ImageBuildError(
            f"Could not connect to the Docker daemon: {exc}"
        ) from exc


def _build_image(
    client: docker.DockerClient,
    dockerfile_content: str,
    context_path: Optional[Path],
    label: str,
) -> Image:
    """Build one Dockerfile state and return the resulting image.

    The build runs through ``docker buildx build``, invoked as a subprocess,
    because BuildKit is what the modern Dockerfile syntax needs: ``COPY
    --chmod``, ``RUN --mount`` and heredoc forms are all rejected by the
    classic builder, and the Docker SDK for Python only speaks to the classic
    ``/build`` endpoint — it has no BuildKit option at all.

    ``--load`` is what keeps the rest of the pipeline working. BuildKit writes
    to its own cache by default and the image never reaches the daemon's image
    store; ``--load`` puts it there, so the size measurement can still fetch it
    with ``client.images.get`` and read ``attrs["Size"]``. The measurement path
    is unchanged and byte precision is preserved (RNF1).

    The Dockerfile is written to a staging directory of its own and passed with
    ``-f``, never into the context. The content analysed is the blob the VCS
    Connector delivered, which may differ from any Dockerfile sitting in the
    context, and writing it outside keeps the exported commit tree untouched.

    Args:
        client: an open Docker client, used only to fetch the built image.
        dockerfile_content: the Dockerfile text for this state.
        context_path: directory whose files accompany the build, or None for a
            context holding nothing but the Dockerfile.
        label: which state is being built ("before"/"after"), used only to
            make the diagnostic message identify the failing side.

    Raises:
        ImageBuildError: buildx is unavailable, the build did not complete, it
            exceeded the timeout, or the built image cannot be fetched (RNF4).
    """
    tag = f"{_TAG_PREFIX}:{uuid.uuid4().hex}"

    with tempfile.TemporaryDirectory(prefix="dockerfile-staging-") as staging:
        dockerfile_file = Path(staging) / _DOCKERFILE_ARCNAME
        # Written as bytes so the state built is the blob byte for byte, with
        # its own line endings, rather than a re-encoded copy.
        dockerfile_file.write_bytes(dockerfile_content.encode("utf-8"))

        context = context_path if context_path is not None else Path(staging)
        command = [
            "docker", "buildx", "build",
            "--load",  # put the result in the daemon's image store
            "--file", str(dockerfile_file),
            "--tag", tag,
            "--progress", "plain",
            str(context),
        ]

        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=_BUILD_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ImageBuildError(
                f"Could not build the '{label}' Dockerfile state: the docker "
                f"command is not available."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ImageBuildError(
                f"Docker build of the '{label}' Dockerfile state did not "
                f"finish within {_BUILD_TIMEOUT_SECONDS} seconds."
            ) from exc

        if completed.returncode != 0:
            raise ImageBuildError(
                f"Docker build of the '{label}' Dockerfile state failed: "
                f"{_build_failure_detail(completed)}"
            )

    # Fetched after the staging directory is gone: the image lives in the
    # daemon now, and this is the handle the size measurement reads.
    try:
        return client.images.get(tag)
    except (ImageNotFound, APIError, DockerException) as exc:
        raise ImageBuildError(
            f"The '{label}' image was built but could not be fetched from the "
            f"daemon: {exc}"
        ) from exc


def _build_failure_detail(completed: "subprocess.CompletedProcess") -> str:
    """The most informative line of a failed build's output.

    buildx writes its progress to stderr, so the reason a build failed is the
    last substantive line rather than the first. Lines that only mark progress
    carry no diagnosis and are skipped.
    """
    text = completed.stderr.decode("utf-8", errors="replace").strip()
    if not text:
        text = completed.stdout.decode("utf-8", errors="replace").strip()
    lines = [
        line.strip() for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not lines:
        return f"exit code {completed.returncode}, no diagnostic output"
    return lines[-1][:400]


def _remove_images(client: docker.DockerClient, images: List[Image]) -> None:
    """Remove every image the preparation built.

    Runs during cleanup, where an exception would mask the failure that
    triggered it, so removal errors are swallowed deliberately: an image that
    is already gone, or that the daemon refuses to delete, must not replace
    the original diagnostic. Each image is attempted independently so one
    failure does not leave the others behind.
    """
    for image in images:
        with contextlib.suppress(ImageNotFound, APIError, DockerException):
            client.images.remove(image.id, force=True)


def _resolved_context(
    context: Optional[Union[str, Path]], label: str
) -> Optional[Path]:
    """Validate one build context path, or pass None through.

    Raises:
        ImageBuildError: the path exists in the call but is not a directory.
    """
    if context is None:
        return None
    resolved = Path(context)
    if not resolved.is_dir():
        raise ImageBuildError(
            f"Build context path for the '{label}' state is not a directory: "
            f"{resolved}"
        )
    return resolved


@contextlib.contextmanager
def build_image_pair(
    dockerfile_before: str,
    dockerfile_after: str,
    context_before: Optional[Union[str, Path]] = None,
    context_after: Optional[Union[str, Path]] = None,
) -> Iterator[BuiltImagePair]:
    """Build both Dockerfile states, yield their references, then remove them.

    The orchestrator wraps the measurement in this context: the builds complete before
    the block is entered, the Performance Analyzer and the Data Extractor run
    concurrently inside it against the yielded references, and both images are
    removed on exit whatever happens — a failed second build, an exception
    raised by either component, or an ordinary return.

    Each state gets its own build context. The two commits may differ in the
    files a COPY reads, not only in the Dockerfile text, and sharing one context
    between them would let a file that changed alongside the refactoring leak
    into both measurements — or, worse, build the earlier state against files
    that only exist in the later one.

    Args:
        dockerfile_before: Dockerfile content at the earlier commit.
        dockerfile_after: Dockerfile content at the later commit.
        context_before: directory whose files accompany the earlier build,
            required when that Dockerfile carries COPY or ADD instructions
            reading from the build context. Defaults to None, a context holding
            only the Dockerfile.
        context_after: the same for the later build.

    Yields:
        The :class:`BuiltImagePair` referencing both built images.

    Raises:
        ImageBuildError: the daemon is unreachable, either context path is not
            a directory, or either build fails (RNF4).
    """
    resolved_before = _resolved_context(context_before, "before")
    resolved_after = _resolved_context(context_after, "after")

    client = _connect()
    built: List[Image] = []
    try:
        image_before = _build_image(
            client, dockerfile_before, resolved_before, "before"
        )
        built.append(image_before)
        image_after = _build_image(client, dockerfile_after, resolved_after, "after")
        built.append(image_after)

        yield BuiltImagePair(
            image_before=image_before.id, image_after=image_after.id
        )
    finally:
        _remove_images(client, built)
        with contextlib.suppress(Exception):
            client.close()


def docker_engine_version() -> str:
    """Version string of the Docker Engine the images were built against.

    Exposed for the Report Generator, which records the version of every
    external tool invoked (RNF5). The preparation is where the Docker
    environment is established, so it is where that version is read.

    Raises:
        ImageBuildError: the daemon is unreachable or does not report a
            version (RNF4).
    """
    client = _connect()
    try:
        return str(client.version()["Version"])
    except (KeyError, TypeError, APIError, DockerException) as exc:
        raise ImageBuildError(
            f"Could not read the Docker Engine version: {exc}"
        ) from exc
    finally:
        with contextlib.suppress(Exception):
            client.close()
