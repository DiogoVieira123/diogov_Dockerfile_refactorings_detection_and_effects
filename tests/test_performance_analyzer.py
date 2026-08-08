"""Unit tests for the Performance Analyzer (RF4, RNF1, RNF4).

The measurement logic, the cleanup guarantees and the exception contract are
exercised against a fake Docker client, so the suite runs without a daemon.
The one test that needs a real daemon builds two Alpine images end to end and
is skipped when Docker is not reachable.
"""

import io
import tarfile

import docker
import pytest

from src.performance_analyzer import (
    PerformanceAnalyzerError,
    SizeMetric,
    _context_archive,
    measure_size_delta,
    measured_image_pair,
)

DOCKERFILE_BEFORE = "FROM ubuntu:22.04\nCMD [\"sh\"]\n"
DOCKERFILE_AFTER = "FROM alpine:3.19\nCMD [\"sh\"]\n"

# Reference values of the PoC-3 acceptance criterion for RF4/RNF1.
POC3_SIZE_BEFORE = 29_748_045
POC3_SIZE_AFTER = 3_429_495


# --- Fake Docker client ---------------------------------------------------------


class FakeImage:
    def __init__(self, image_id: str, size):
        self.id = image_id
        self.attrs = {} if size is None else {"Size": size}


class FakeImages:
    """Stands in for client.images, recording what the analyzer asked of it."""

    def __init__(self, sizes, failure=None):
        self._sizes = list(sizes)
        self._failure = failure  # exception raised on the second build
        self.builds = []  # kwargs of every build call
        self.removed = []  # ids passed to remove()

    def build(self, **kwargs):
        self.builds.append(kwargs)
        if self._failure is not None and len(self.builds) == 2:
            raise self._failure
        size = self._sizes[len(self.builds) - 1]
        return FakeImage(f"sha256:image{len(self.builds)}", size), []

    def remove(self, image_id, force=False):
        self.removed.append(image_id)


class FakeClient:
    def __init__(self, sizes=(1, 2), failure=None):
        self.images = FakeImages(sizes, failure)
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def fake_docker(monkeypatch):
    """Install a fake client and hand the test a factory to configure it."""

    created = {}

    def install(sizes=(POC3_SIZE_BEFORE, POC3_SIZE_AFTER), failure=None):
        client = FakeClient(sizes, failure)
        created["client"] = client
        monkeypatch.setattr(docker, "from_env", lambda: client)
        return client

    return install


# --- SizeMetric: the RF4 computation --------------------------------------------


def test_size_metric_computes_the_poc3_reference_delta():
    metric = SizeMetric.from_sizes(POC3_SIZE_BEFORE, POC3_SIZE_AFTER)
    assert metric.delta_size == -26_318_550


def test_size_metric_is_expressed_only_in_bytes():
    # RF4 measures the size delta exclusively in bytes, the same absolute-value
    # form the other three pipeline metrics use.
    assert SizeMetric._fields == ("size_before", "size_after", "delta_size")


def test_size_metric_keeps_byte_resolution_for_micro_variations():
    # RNF1: the +417 bytes of the R09 experiment must survive intact, where
    # CLI rounding would report zero.
    metric = SizeMetric.from_sizes(3_633_775, 3_634_192)
    assert metric.delta_size == 417


def test_size_metric_delta_is_signed_after_minus_before():
    assert SizeMetric.from_sizes(100, 250).delta_size == 150
    assert SizeMetric.from_sizes(250, 100).delta_size == -150
    assert SizeMetric.from_sizes(100, 100).delta_size == 0


def test_size_metric_tolerates_a_zero_before_size():
    assert SizeMetric.from_sizes(0, 500).delta_size == 500


# --- Measurement ----------------------------------------------------------------


def test_measure_size_delta_returns_both_sizes_and_the_delta(fake_docker):
    fake_docker()
    metric = measure_size_delta(DOCKERFILE_BEFORE, DOCKERFILE_AFTER)
    assert metric.size_before == POC3_SIZE_BEFORE
    assert metric.size_after == POC3_SIZE_AFTER
    assert metric.delta_size == -26_318_550


def test_measured_image_pair_exposes_the_image_ids(fake_docker):
    # The Data Extractor scans these images rather than rebuilding them.
    fake_docker()
    with measured_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER) as (
        metric,
        id_before,
        id_after,
    ):
        assert metric.delta_size == -26_318_550
        assert id_before != id_after


def test_build_sends_an_in_memory_context_and_not_a_path(fake_docker):
    client = fake_docker()
    measure_size_delta(DOCKERFILE_BEFORE, DOCKERFILE_AFTER)
    assert len(client.images.builds) == 2
    for call in client.images.builds:
        assert call["custom_context"] is True
        assert isinstance(call["fileobj"], io.BytesIO)
        assert "path" not in call  # never a directory handed to the daemon
        assert call["tag"].islower()  # Docker rejects upper case in tags


# --- Resource cleanup -----------------------------------------------------------


def test_both_images_are_removed_after_a_successful_measurement(fake_docker):
    client = fake_docker()
    measure_size_delta(DOCKERFILE_BEFORE, DOCKERFILE_AFTER)
    assert client.images.removed == ["sha256:image1", "sha256:image2"]
    assert client.closed


def test_the_first_image_is_removed_when_the_second_build_fails(fake_docker):
    # The leak that would otherwise fill the disk over a catalogue-wide run.
    client = fake_docker(failure=docker.errors.BuildError("boom", build_log=[]))
    with pytest.raises(PerformanceAnalyzerError):
        measure_size_delta(DOCKERFILE_BEFORE, DOCKERFILE_AFTER)
    assert client.images.removed == ["sha256:image1"]


def test_images_are_removed_when_the_caller_raises_inside_the_context(fake_docker):
    client = fake_docker()
    with pytest.raises(ValueError):
        with measured_image_pair(DOCKERFILE_BEFORE, DOCKERFILE_AFTER):
            raise ValueError("caller failed mid-analysis")
    assert client.images.removed == ["sha256:image1", "sha256:image2"]


def test_a_failing_removal_does_not_mask_the_original_error(fake_docker):
    client = fake_docker(failure=docker.errors.BuildError("boom", build_log=[]))

    def refuse(image_id, force=False):
        raise docker.errors.APIError("daemon refused the removal")

    client.images.remove = refuse
    # The build failure must surface, not the cleanup failure.
    with pytest.raises(PerformanceAnalyzerError, match="build"):
        measure_size_delta(DOCKERFILE_BEFORE, DOCKERFILE_AFTER)


# --- Exception contract (RNF4) --------------------------------------------------


def test_unreachable_daemon_raises_performance_analyzer_error(monkeypatch):
    def unavailable():
        raise docker.errors.DockerException("daemon not running")

    monkeypatch.setattr(docker, "from_env", unavailable)
    with pytest.raises(PerformanceAnalyzerError, match="Docker daemon"):
        measure_size_delta(DOCKERFILE_BEFORE, DOCKERFILE_AFTER)


def test_build_failure_names_the_offending_state(fake_docker):
    fake_docker(failure=docker.errors.BuildError("invalid instruction", build_log=[]))
    with pytest.raises(PerformanceAnalyzerError, match="'after'"):
        measure_size_delta(DOCKERFILE_BEFORE, DOCKERFILE_AFTER)


def test_api_error_during_build_raises_performance_analyzer_error(fake_docker):
    fake_docker(failure=docker.errors.APIError("daemon went away"))
    with pytest.raises(PerformanceAnalyzerError, match="daemon error"):
        measure_size_delta(DOCKERFILE_BEFORE, DOCKERFILE_AFTER)


def test_missing_size_attribute_raises_performance_analyzer_error(fake_docker):
    fake_docker(sizes=(POC3_SIZE_BEFORE, None))
    with pytest.raises(PerformanceAnalyzerError, match="inspect the size"):
        measure_size_delta(DOCKERFILE_BEFORE, DOCKERFILE_AFTER)


def test_non_integer_size_raises_performance_analyzer_error(fake_docker):
    # A string size is exactly what the rejected CLI path would deliver.
    fake_docker(sizes=(POC3_SIZE_BEFORE, "3.4MB"))
    with pytest.raises(PerformanceAnalyzerError, match="integer byte count"):
        measure_size_delta(DOCKERFILE_BEFORE, DOCKERFILE_AFTER)


def test_a_context_path_that_is_not_a_directory_is_rejected(tmp_path):
    missing = tmp_path / "no-such-context"
    with pytest.raises(PerformanceAnalyzerError, match="not a directory"):
        measure_size_delta(DOCKERFILE_BEFORE, DOCKERFILE_AFTER, context_path=missing)


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


def test_measuring_writes_nothing_to_the_working_directory(fake_docker, tmp_path):
    (tmp_path / "app.txt").write_text("payload", encoding="utf-8")
    before = {entry.name for entry in tmp_path.iterdir()}

    fake_docker()
    measure_size_delta(DOCKERFILE_BEFORE, DOCKERFILE_AFTER, context_path=tmp_path)

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
    """RF4 end to end: two real builds, a real byte delta, no image left behind."""
    before = "FROM alpine:3.20\nRUN echo before > /marker\n"
    after = "FROM alpine:3.20\nRUN echo after-with-more-content > /marker\n"

    client = docker.from_env()
    images_before_run = {image.id for image in client.images.list()}

    metric = measure_size_delta(before, after)

    assert metric.size_before > 0 and metric.size_after > 0
    assert metric.delta_size == metric.size_after - metric.size_before
    # Nothing the analysis built survives it.
    assert {image.id for image in client.images.list()} == images_before_run
    client.close()
