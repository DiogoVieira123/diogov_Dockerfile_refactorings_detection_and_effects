"""Unit tests for the image preparation phase (RNF4).

The build invocation, the cleanup guarantees and the exception contract are
exercised against a fake Docker client, so the suite runs without a daemon.
The one test that needs a real daemon builds two Alpine images end to end and
is skipped when Docker is not reachable.
"""

import io
import tarfile

import docker
import pytest

from src.image_builder import (
    ImageBuildError,
    _context_archive,
    build_image_pair,
    docker_engine_version,
)

DOCKERFILE_BEFORE = "FROM ubuntu:22.04\nCMD [\"sh\"]\n"
DOCKERFILE_AFTER = "FROM alpine:3.19\nCMD [\"sh\"]\n"


# --- Fake Docker client ---------------------------------------------------------


class FakeImage:
    def __init__(self, image_id: str):
        self.id = image_id


class FakeImages:
    """Stands in for client.images, recording what the builder asked of it."""

    def __init__(self, failure=None):
        self._failure = failure  # exception raised on the second build
        self.builds = []  # kwargs of every build call
        self.removed = []  # ids passed to remove()

    def build(self, **kwargs):
        self.builds.append(kwargs)
        if self._failure is not None and len(self.builds) == 2:
            raise self._failure
        return FakeImage(f"sha256:image{len(self.builds)}"), []

    def remove(self, image_id, force=False):
        self.removed.append(image_id)


class FakeClient:
    def __init__(self, failure=None, version="29.1.3"):
        self.images = FakeImages(failure)
        self._version = version
        self.closed = False

    def version(self):
        return {"Version": self._version}

    def close(self):
        self.closed = True


@pytest.fixture
def fake_docker(monkeypatch):
    """Install a fake client and hand the test a factory to configure it."""

    def install(failure=None, version="29.1.3"):
        client = FakeClient(failure, version)
        monkeypatch.setattr(docker, "from_env", lambda: client)
        return client

    return install


# --- Building -------------------------------------------------------------------


def test_build_image_pair_yields_both_image_references(fake_docker):
    fake_docker()
    with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER) as pair:
        assert pair.image_before == "sha256:image1"
        assert pair.image_after == "sha256:image2"


def test_the_pair_carries_identifiers_and_not_sdk_objects(fake_docker):
    # Stage 2 consumes references, sharing no object graph with this phase.
    fake_docker()
    with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER) as pair:
        assert isinstance(pair.image_before, str)
        assert isinstance(pair.image_after, str)


def test_build_sends_an_in_memory_context_and_not_a_path(fake_docker):
    client = fake_docker()
    with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
        pass
    assert len(client.images.builds) == 2
    for call in client.images.builds:
        assert call["custom_context"] is True
        assert isinstance(call["fileobj"], io.BytesIO)
        assert "path" not in call  # never a directory handed to the daemon
        assert call["tag"].islower()  # Docker rejects upper case in tags


def test_docker_engine_version_is_reported_for_rnf5(fake_docker):
    fake_docker(version="29.1.3")
    assert docker_engine_version() == "29.1.3"


# --- Resource cleanup -----------------------------------------------------------


def test_both_images_are_removed_when_the_context_closes(fake_docker):
    client = fake_docker()
    with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
        assert client.images.removed == []  # still available to Stage 2
    assert client.images.removed == ["sha256:image1", "sha256:image2"]
    assert client.closed


def test_the_first_image_is_removed_when_the_second_build_fails(fake_docker):
    # The leak that would otherwise fill the disk over a catalogue-wide run.
    client = fake_docker(failure=docker.errors.BuildError("boom", build_log=[]))
    with pytest.raises(ImageBuildError):
        with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
            pass
    assert client.images.removed == ["sha256:image1"]


def test_images_are_removed_when_a_stage_2_component_raises(fake_docker):
    client = fake_docker()
    with pytest.raises(ValueError):
        with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
            raise ValueError("a Stage 2 component failed")
    assert client.images.removed == ["sha256:image1", "sha256:image2"]


def test_a_failing_removal_does_not_mask_the_original_error(fake_docker):
    client = fake_docker(failure=docker.errors.BuildError("boom", build_log=[]))

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


def test_build_failure_names_the_offending_state(fake_docker):
    fake_docker(failure=docker.errors.BuildError("invalid instruction", build_log=[]))
    with pytest.raises(ImageBuildError, match="'after'"):
        with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
            pass


def test_api_error_during_build_raises_image_build_error(fake_docker):
    fake_docker(failure=docker.errors.APIError("daemon went away"))
    with pytest.raises(ImageBuildError, match="daemon error"):
        with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
            pass


def test_a_context_path_that_is_not_a_directory_is_rejected(tmp_path):
    missing = tmp_path / "no-such-context"
    with pytest.raises(ImageBuildError, match="not a directory"):
        with build_image_pair(
            DOCKERFILE_BEFORE, DOCKERFILE_AFTER, context_path=missing
        ):
            pass


# --- Build context assembly -----------------------------------------------------


def _archive_names(stream: io.BytesIO):
    with tarfile.open(fileobj=stream, mode="r") as archive:
        return set(archive.getnames())


def test_context_archive_carries_the_dockerfile_content():
    stream = _context_archive(DOCKERFILE_AFTER, None)
    with tarfile.open(fileobj=stream, mode="r") as archive:
        extracted = archive.extractfile("Dockerfile").read().decode("utf-8")
    assert extracted == DOCKERFILE_AFTER


def test_context_archive_includes_the_context_files(tmp_path):
    (tmp_path / "app.txt").write_text("payload", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "setup.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    names = _archive_names(_context_archive(DOCKERFILE_AFTER, tmp_path))
    assert names == {"Dockerfile", "app.txt", "scripts/setup.sh"}


def test_context_archive_replaces_a_dockerfile_found_in_the_context(tmp_path):
    # The state under analysis wins over whatever sits in the directory.
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    stream = _context_archive(DOCKERFILE_AFTER, tmp_path)
    with tarfile.open(fileobj=stream, mode="r") as archive:
        assert archive.getnames().count("Dockerfile") == 1
        content = archive.extractfile("Dockerfile").read().decode("utf-8")
    assert content == DOCKERFILE_AFTER


def test_context_archive_excludes_repository_metadata(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (tmp_path / "app.txt").write_text("payload", encoding="utf-8")

    assert _archive_names(_context_archive(DOCKERFILE_AFTER, tmp_path)) == {
        "Dockerfile",
        "app.txt",
    }


def test_building_writes_nothing_to_the_working_directory(fake_docker, tmp_path):
    (tmp_path / "app.txt").write_text("payload", encoding="utf-8")
    before = {entry.name for entry in tmp_path.iterdir()}

    fake_docker()
    with build_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER, context_path=tmp_path):
        pass

    assert {entry.name for entry in tmp_path.iterdir()} == before


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
        # Stage 2 finds both images present and inspectable.
        assert client.images.get(pair.image_before).attrs["Size"] > 0
        assert client.images.get(pair.image_after).attrs["Size"] > 0

    # Nothing the preparation phase built survives it.
    assert {image.id for image in client.images.list()} == images_before_run
    client.close()
