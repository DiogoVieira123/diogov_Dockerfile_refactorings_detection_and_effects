"""Pipeline orchestrator — chains the five components (Chapter 5, Section 5.1).

This is the module that owns the sequence. Every component is a library that
knows nothing of its neighbours; the ordering, the parallelism and the resource
lifetime all live here, which is what keeps the components independently
testable and independently replaceable.

The four stages of the design run as follows:

    Stage 1   Data collection — vcs_connector
              Reaches into the Git object model to extract the Dockerfile
              content at each of the two commits, at blob level.

    Stage 2   Refactoring detection — detection_engine
              Decomposes both states with dockerfile-parse and applies the
              rules that identify the refactoring type.

    Stage 3   Empirical evaluation and measurement — commit_context,
              image_builder, performance_analyzer, data_extractor
              Runs in two steps. The preparation exports each commit's file
              tree through Git archive and builds the image pair, each state
              isolated in its own context. The measurement then runs in
              parallel through a ThreadPoolExecutor: image size (delta Size),
              vulnerabilities (delta CVEs), static warnings (delta Warnings)
              and logical instructions (delta Instr).

              The build belongs to the preparation rather than inside either
              measurement component because both of them consume the images:
              leaving it in either would make the other wait on it, and giving
              each its own build would duplicate the most expensive operation
              in the pipeline. Neither measurement component reads a value
              produced by the other, so the two run without coordination and
              the elapsed time is that of the slower one.

    Stage 4   Report generation — report_generator
              Aggregates the metrics established in Stage 3, compiles the
              technical provenance block and writes the final output artifacts.

Both images and both exported trees are removed when Stage 3's contexts close,
whatever happened inside them, so a failed run leaves nothing behind.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import io
import sys
import tarfile
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Iterator, Union

import git

from src.data_extractor import extract_metrics, tool_provenance
from src.detection_engine import detect_refactorings
from src.image_builder import build_image_pair, docker_engine_version
from src.performance_analyzer import measure_size_delta
from src.report_generator import ReportArtifacts, generate_report
from src.vcs_connector import retrieve_dockerfile_pair

DEFAULT_DOCKERFILE_PATH = "Dockerfile"


class CommitContextError(Exception):
    """The file tree of a commit could not be exported for the build context.

    RNF4: a repository that cannot be opened, a treeish Git does not recognise,
    or an archive that cannot be unpacked surfaces as this exception rather than
    as a raw GitPython or tarfile error, so the orchestrator can report which
    stage failed.
    """


@contextlib.contextmanager
def commit_context(
    repository_path: Union[str, Path], sha: str
) -> Iterator[Path]:
    """Export the file tree of one commit into a temporary directory.

    The build context must be the repository as it stood at the commit being
    measured, not as it stands now. Two commits routinely differ in the files a
    COPY reads, and building both states against today's working tree would let
    an unrelated later edit contaminate the earlier measurement, or build the
    earlier state against files that did not exist yet.

    ``repo.archive`` writes the tree as a tar stream without touching the
    working tree or the index, which keeps the export consistent with the
    blob-level access the VCS Connector already uses (RF1): nothing is checked
    out and the repository is left exactly as it was found.

    The directory is removed when the context closes, whatever happens inside
    it, so a catalogue-wide run leaks nothing to disk.

    Args:
        repository_path: path of the local Git repository.
        sha: commit whose tree is exported; abbreviated forms are accepted.

    Yields:
        Path of the temporary directory holding the exported tree.

    Raises:
        CommitContextError: the repository cannot be opened, the commit is
            unknown, or the archive cannot be unpacked (RNF4).
    """
    try:
        repo = git.Repo(str(repository_path))
    except (git.InvalidGitRepositoryError, git.NoSuchPathError) as exc:
        raise CommitContextError(
            f"Could not open the Git repository at '{repository_path}': {exc}"
        ) from exc

    temporary = tempfile.TemporaryDirectory(prefix="dockerfile-analysis-")
    try:
        destination = Path(temporary.name)
        stream = io.BytesIO()
        try:
            repo.archive(stream, treeish=sha, format="tar")
        except (git.GitCommandError, git.BadName, ValueError) as exc:
            raise CommitContextError(
                f"Could not export the file tree of commit '{sha}': {exc}"
            ) from exc

        stream.seek(0)
        try:
            with tarfile.open(fileobj=stream, mode="r") as archive:
                # filter="data" rejects absolute paths, parent-directory
                # traversal, links pointing outside the destination and device
                # nodes, so a crafted repository cannot write beyond the
                # temporary directory.
                archive.extractall(destination, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise CommitContextError(
                f"Could not unpack the file tree of commit '{sha}': {exc}"
            ) from exc

        yield destination
    finally:
        temporary.cleanup()


def _library_version(package: str) -> str:
    """Installed version of a dependency, for the RNF5 provenance block."""
    try:
        return version(package)
    except PackageNotFoundError:  # pragma: no cover — dependency always present
        return "unknown"


def _collect_tool_versions() -> dict:
    """Version of every external tool the analysis invoked (RNF5).

    Gathered after the measurements rather than before, so the Trivy
    vulnerability database version is the one the scans actually used: the
    database is downloaded into the shared cache during the first scan, and a
    query made before that would report it as absent.
    """
    provenance = tool_provenance()
    return {
        "docker_engine": docker_engine_version(),
        "hadolint": provenance.hadolint_version,
        "trivy": provenance.trivy_version,
        "trivy_vulnerability_db": provenance.trivy_db_version,
        "dockerfile_parse": _library_version("dockerfile-parse"),
        "gitpython": _library_version("GitPython"),
        "docker_sdk": _library_version("docker"),
        "python": sys.version.split()[0],
    }


def run_analysis(
    repository_path: Union[str, Path],
    commit_before: str,
    commit_after: str,
    output_dir: Union[str, Path],
    *,
    dockerfile_path: str = DEFAULT_DOCKERFILE_PATH,
) -> ReportArtifacts:
    """Run the complete pipeline and write the report artifacts.

    Each state is built against its own commit's file tree, exported to a
    temporary directory that is removed when the analysis ends. The two builds
    therefore see the repository exactly as it stood at each commit, which is
    what makes the size delta attributable to the change between them rather
    than to whatever the working tree happens to hold today.

    Args:
        repository_path: path of a local Git repository, already cloned.
        commit_before: SHA of the earlier commit; abbreviated forms are
            accepted.
        commit_after: SHA of the later commit.
        output_dir: directory the three artifacts are written into; created if
            absent.
        dockerfile_path: the single Dockerfile path tracked through both
            commits, relative to the repository root (RF1).

    Returns:
        The paths of the three written artifacts.

    Raises:
        VcsConnectorError: the repository, a commit, or the Dockerfile is not
            found.
        DockerfileParseError: a Dockerfile state cannot be parsed.
        CommitContextError: a commit's file tree cannot be exported.
        ImageBuildError: the daemon is unreachable or either build fails.
        PerformanceAnalyzerError: an image size cannot be measured.
        DataExtractorError: Hadolint or Trivy fails.
    """
    repository = Path(repository_path)

    # --- Stages 1 and 2: data collection, then refactoring detection ------
    pair = retrieve_dockerfile_pair(
        str(repository), commit_before, commit_after, dockerfile_path
    )
    before, after = pair.dockerfile_a, pair.dockerfile_b
    detections = detect_refactorings(before, after)

    # --- Stage 3, preparation: each state's own commit tree, one build each
    # ExitStack holds both temporary directories open for as long as the builds
    # need them and unwinds them in reverse order on the way out, whether the
    # block ends normally or by exception.
    with contextlib.ExitStack() as trees:
        context_before = trees.enter_context(commit_context(repository, commit_before))
        context_after = trees.enter_context(commit_context(repository, commit_after))
        images = trees.enter_context(
            build_image_pair(
                before,
                after,
                context_before=context_before,
                context_after=context_after,
            )
        )

        # --- Stage 3, measurement: independent components, concurrent -----
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            size_future = pool.submit(
                measure_size_delta, images.image_before, images.image_after
            )
            data_future = pool.submit(
                extract_metrics, before, after, images.image_before, images.image_after
            )
            # Both futures are resolved before either result is used, so a
            # failure in one does not leave the other running past the exit of
            # the preparation's context.
            size_error = data_error = None
            try:
                size_metric = size_future.result()
            except Exception as exc:  # noqa: BLE001 — re-raised below, in order
                size_error, size_metric = exc, None
            try:
                extraction = data_future.result()
            except Exception as exc:  # noqa: BLE001 — re-raised below, in order
                data_error, extraction = exc, None
            if size_error is not None:
                raise size_error
            if data_error is not None:
                raise data_error

        tool_versions = _collect_tool_versions()

    # --- Stage 4: aggregation ---------------------------------------------
    return generate_report(
        detections,
        size_metric,
        extraction,
        output_dir=output_dir,
        repository=str(repository),
        dockerfile_path=dockerfile_path,
        commit_before=commit_before,
        commit_after=commit_after,
        tool_versions=tool_versions,
    )
