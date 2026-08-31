"""Unit tests for the Stage 3 preparation step (RNF4).

The build is a ``docker buildx build`` subprocess, so it is faked at
``subprocess.run``; fetching the built image still goes through the Docker SDK,
which is faked at the client. Neither needs a daemon. The two end-to-end tests
build real images and are skipped when Docker is not reachable.
"""

import subprocess
from pathlib import Path

import docker
import pytest

from src import image_builder
from src.image_builder import (
    ImageBuildError,
    build_image_pair,
    docker_engine_version,
)

DOCKERFILE_BEFORE = "FROM ubuntu:22.04\nCMD [\"sh\"]\n"
DOCKERFILE_AFTER = "FROM alpine:3.19\nCMD [\"sh\"]\n"


# --- Fakes -----------------------------------------------------------------------


class FakeImage:
    def __init__(self, image_id: str):
        self.id = image_id


class FakeImages:
    """Stands in for client.images: serves built images and records removals."""

    def __init__(self, fetch_failure=None):
        self._fetch_failure = fetch_failure
        self.fetched = []
        self.removed = []

    def get(self, reference):
        self.fetched.append(reference)
        if self._fetch_failure is not None:
            raise self._fetch_failure
        return FakeImage("sha256:image{}".format(len(self.fetched)))

    def remove(self, image_id, force=False):
        self.removed.append(image_id)

    def build(self, **kwargs):  # pragma: no cover — must never be called
        raise AssertionError("the build must go through buildx, not the SDK")


class FakeClient:
    def __init__(self, fetch_failure=None, version="29.1.3"):
        self.images = FakeImages(fetch_failure)
        self._version = version
        self.closed = False

    def version(self):
        return {"Version": self._version}

    def close(self):
        self.closed = True


class FakeBuild:
    """Stands in for subprocess.run, recording every buildx invocation."""

    def __init__(self, failure=None, returncode=0, stderr=b""):
        self.failure = failure  # exception raised on the second build
        self.returncode = returncode
        self.stderr = stderr
        self.commands = []
        self.staged = []  # (dockerfile path, content) seen at call time

    def __call__(self, command, stdout=None, stderr=None, timeout=None, check=False):
        self.commands.append(list(command))
        # The staged Dockerfile only exists while the build runs, so it is read
        # here rather than after the call.
        if "--file" in command:
            staged = Path(command[command.index("--file") + 1])
            self.staged.append((staged, staged.read_bytes() if staged.is_file() else None))
        if self.failure is not None and len(self.commands) == 2:
            raise self.failure
        return subprocess.CompletedProcess(command, self.returncode, b"", self.stderr)


@pytest.fixture
def fake_build(monkeypatch):
    """Install a fake buildx subprocess and a fake Docker client."""

    def install(failure=None, returncode=0, stderr=b"", fetch_failure=None,
                version="29.1.3"):
        builder = FakeBuild(failure, returncode, stderr)
        client = FakeClient(fetch_failure, version)
        monkeypatch.setattr(subprocess, "run", builder)
        monkeypatch.setattr(docker, "from_env", lambda: client)
        return builder, client

    return install


# --- The buildx invocation ---------------------------------------------------------


def test_build_image_pair_yields_both_image_references(fake_build):
    fake_build()
    with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER) as pair:
        assert pair.image_before == "sha256:image1"
        assert pair.image_after == "sha256:image2"


def test_the_pair_carries_identifiers_and_not_sdk_objects(fake_build):
    # The measurement consumes references, sharing no object graph with this step.
    fake_build()
    with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER) as pair:
        assert isinstance(pair.image_before, str)
        assert isinstance(pair.image_after, str)


def test_the_build_runs_through_buildx(fake_build):
    # The classic builder rejects COPY --chmod and the rest of the modern
    # syntax, and the SDK cannot reach BuildKit at all.
    builder, _ = fake_build()
    with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
        pass
    assert len(builder.commands) == 2
    for command in builder.commands:
        assert command[:4] == ["docker", "buildx", "build", "--load"]


def test_the_load_flag_is_always_passed(fake_build):
    # Without --load BuildKit keeps the image in its own cache and it never
    # reaches the daemon, so the size measurement would find nothing.
    builder, _ = fake_build()
    with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
        pass
    assert all("--load" in command for command in builder.commands)


def test_each_build_is_tagged_in_lower_case(fake_build):
    builder, _ = fake_build()
    with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
        pass
    tags = [c[c.index("--tag") + 1] for c in builder.commands]
    assert all(tag.islower() for tag in tags)  # Docker rejects upper case
    assert tags[0] != tags[1], "the two states must not share a tag"


def test_the_context_is_the_last_positional_argument(fake_build, tmp_path):
    context = tmp_path / "ctx"
    context.mkdir()
    builder, _ = fake_build()
    with build_image_pair(
        DOCKERFILE_BEFORE, DOCKERFILE_AFTER,
        context_before=context, context_after=context,
    ):
        pass
    assert all(Path(command[-1]) == context for command in builder.commands)


def test_the_dockerfile_is_staged_outside_the_context(fake_build, tmp_path):
    # The state under analysis is the blob the VCS Connector delivered, which
    # may differ from a Dockerfile sitting in the context; staging it elsewhere
    # leaves the exported commit tree exactly as Git wrote it.
    context = tmp_path / "ctx"
    context.mkdir()
    (context / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    before = {entry.name for entry in context.iterdir()}

    builder, _ = fake_build()
    with build_image_pair(
        DOCKERFILE_BEFORE, DOCKERFILE_AFTER,
        context_before=context, context_after=context,
    ):
        pass

    for staged, _content in builder.staged:
        assert context not in staged.parents
    assert {entry.name for entry in context.iterdir()} == before


def test_the_staged_dockerfile_holds_the_analysed_content(fake_build):
    builder, _ = fake_build()
    with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
        pass
    contents = [content for _path, content in builder.staged]
    assert contents == [DOCKERFILE_BEFORE.encode(), DOCKERFILE_AFTER.encode()]


def test_the_staging_directory_does_not_survive_the_build(fake_build):
    builder, _ = fake_build()
    with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
        pass
    for staged, _content in builder.staged:
        assert not staged.exists()


def test_the_built_image_is_fetched_through_the_sdk(fake_build):
    # RNF1: the size is read from attrs["Size"] via the SDK, and this is the
    # handle that makes it reachable.
    builder, client = fake_build()
    with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
        pass
    tags = [c[c.index("--tag") + 1] for c in builder.commands]
    assert client.images.fetched == tags


def test_docker_engine_version_is_reported_for_rnf5(fake_build):
    fake_build(version="29.1.3")
    assert docker_engine_version() == "29.1.3"


# --- Resource cleanup -----------------------------------------------------------


def test_both_images_are_removed_when_the_context_closes(fake_build):
    _, client = fake_build()
    with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
        assert client.images.removed == []  # still available to the measurement
    assert client.images.removed == ["sha256:image1", "sha256:image2"]
    assert client.closed


def test_the_first_image_is_removed_when_the_second_build_fails(fake_build):
    # The leak that would otherwise fill the disk over a catalogue-wide run.
    _, client = fake_build(failure=OSError("boom"))
    with pytest.raises(Exception):
        with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
            pass
    assert client.images.removed == ["sha256:image1"]


def test_images_are_removed_when_a_measurement_component_raises(fake_build):
    _, client = fake_build()
    with pytest.raises(ValueError):
        with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
            raise ValueError("a measurement component failed")
    assert client.images.removed == ["sha256:image1", "sha256:image2"]


def test_a_failing_removal_does_not_mask_the_original_error(fake_build):
    _, client = fake_build(returncode=1, stderr=b"ERROR: something broke")

    def refuse(image_id, force=False):
        raise docker.errors.APIError("daemon refused the removal")

    client.images.remove = refuse
    # The build failure must surface, not the cleanup failure.
    with pytest.raises(ImageBuildError, match="build"):
        with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
            pass


# --- Exception contract (RNF4) --------------------------------------------------


def test_unreachable_daemon_raises_image_build_error(monkeypatch):
    def unavailable():
        raise docker.errors.DockerException("daemon not running")

    monkeypatch.setattr(docker, "from_env", unavailable)
    with pytest.raises(ImageBuildError, match="Docker daemon"):
        with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
            pass


def test_a_failed_build_names_the_offending_state(fake_build):
    fake_build(returncode=1, stderr=b"ERROR: failed to solve: invalid instruction")
    with pytest.raises(ImageBuildError, match="'before'"):
        with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
            pass


def test_a_failed_build_reports_the_diagnostic_line(fake_build):
    fake_build(
        returncode=1,
        stderr=b"#5 [2/3] RUN false\n#5 ERROR: process did not complete\nfailed to solve: exit code 1",
    )
    with pytest.raises(ImageBuildError, match="failed to solve"):
        with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
            pass


def test_a_build_with_no_diagnostic_output_still_reports_its_exit_code(fake_build):
    fake_build(returncode=7, stderr=b"")
    with pytest.raises(ImageBuildError, match="exit code 7"):
        with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
            pass


def test_an_absent_docker_command_raises_image_build_error(fake_build, monkeypatch):
    _, client = fake_build()

    def missing(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(ImageBuildError, match="docker command is not available"):
        with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
            pass


def test_a_build_that_overruns_its_timeout_raises_image_build_error(fake_build, monkeypatch):
    fake_build()

    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired("docker", image_builder._BUILD_TIMEOUT_SECONDS)

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(ImageBuildError, match="did not finish"):
        with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
            pass


def test_an_image_that_cannot_be_fetched_raises_image_build_error(fake_build):
    fake_build(fetch_failure=docker.errors.ImageNotFound("gone"))
    with pytest.raises(ImageBuildError, match="could not be fetched"):
        with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
            pass


def test_a_context_path_that_is_not_a_directory_is_rejected(tmp_path):
    missing = tmp_path / "no-such-context"
    with pytest.raises(ImageBuildError, match="not a directory"):
        with build_image_pair(
            DOCKERFILE_BEFORE, DOCKERFILE_AFTER, context_before=missing
        ):
            pass


# --- Integration: requires a running Docker daemon --------------------------------


def _daemon_available() -> bool:
    try:
        client = docker.from_env()
        client.ping()
        client.close()
        return True
    except Exception:  # noqa: BLE001 — any failure means no usable daemon
        return False


@pytest.mark.skipif(not _daemon_available(), reason="Docker daemon not reachable")
def test_end_to_end_against_a_real_daemon():
    """Two real builds, both images usable inside the block, none left behind."""
    before = "FROM alpine:3.20\nRUN echo before > /marker\n"
    after = "FROM alpine:3.20\nRUN echo after-with-more-content > /marker\n"

    client = docker.from_env()
    images_before_run = {image.id for image in client.images.list()}

    with build_image_pair(before, after) as pair:
        # The measurement finds both images present and inspectable.
        assert client.images.get(pair.image_before).attrs["Size"] > 0
        assert client.images.get(pair.image_after).attrs["Size"] > 0

    # Nothing the preparation built survives it.
    assert {image.id for image in client.images.list()} == images_before_run
    client.close()


@pytest.mark.skipif(not _daemon_available(), reason="Docker daemon not reachable")
def test_buildkit_only_syntax_builds(tmp_path):
    """COPY --chmod is what the classic builder rejects; BuildKit accepts it."""
    (tmp_path / "payload.txt").write_text("content\n", encoding="utf-8")
    dockerfile = (
        "FROM alpine:3.20\n"
        "COPY --chmod=755 payload.txt /opt/payload.txt\n"
    )

    with build_image_pair(
        dockerfile, dockerfile,
        context_before=tmp_path, context_after=tmp_path,
    ) as pair:
        assert pair.image_before and pair.image_after
