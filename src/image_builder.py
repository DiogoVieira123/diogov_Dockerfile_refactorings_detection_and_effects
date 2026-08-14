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

Two properties govern the implementation:

* **Nothing is written to the working directory.** The build context is
  assembled as a tar archive in memory and handed to the daemon as a byte
  stream, so analysing a repository never leaves temporary Dockerfiles or
  context copies behind on the caller's disk.
* **No image outlives the analysis.** Both images are removed when the
  preparation context closes, whatever happens inside it. Left unchecked, a
  catalogue-wide run would accumulate dozens of images and exhaust the
  daemon's storage.

All Docker SDK failures — daemon unavailable, build error — surface as
:class:`ImageBuildError` (RNF4), so the pipeline can distinguish a preparation
failure from a defect of its own or from a measurement failure downstream.
"""

from __future__ import annotations

import contextlib
import io
import tarfile
import uuid
from pathlib import Path
from typing import Iterator, List, NamedTuple, Optional, Union

import docker
from docker.errors import APIError, BuildError, DockerException, ImageNotFound
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
        ImageBuildError: the daemon is not running or not reachable through
            the environment's Docker configuration (RNF4).
    """
    try:
        return docker.from_env()
    except DockerException as exc:
        raise ImageBuildError(
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
        ImageBuildError: the build did not complete (RNF4).
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
        raise ImageBuildError(
            f"Docker build of the '{label}' Dockerfile state failed: {exc}"
        ) from exc
    except (APIError, DockerException) as exc:
        raise ImageBuildError(
            f"Docker daemon error while building the '{label}' Dockerfile "
            f"state: {exc}"
        ) from exc
    return image


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
