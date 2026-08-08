"""Unit tests for the Performance Analyzer (RF4, RNF1, RNF4).

The component measures images the preparation phase already built, so the
measurement logic and the exception contract run against a fake Docker client
and need no daemon. The end-to-end test builds two real images through
``image_builder`` and is skipped when Docker is not reachable.
"""

import docker
import pytest

from src.image_builder import build_image_pair
from src.performance_analyzer import (
    PerformanceAnalyzerError,
    SizeMetric,
    measure_size_delta,
)

IMAGE_BEFORE = "sha256:imagebefore"
IMAGE_AFTER = "sha256:imageafter"

# Reference values of the PoC-3 acceptance criterion for RF4/RNF1.
POC3_SIZE_BEFORE = 29_748_045
POC3_SIZE_AFTER = 3_429_495


# --- Fake Docker client ---------------------------------------------------------


class FakeImage:
    def __init__(self, size):
        self.attrs = {} if size is None else {"Size": size}


class FakeImages:
    """Stands in for client.images, serving sizes by image reference."""

    def __init__(self, sizes, failure=None):
        self._sizes = sizes  # reference -> size
        self._failure = failure  # exception raised by get()
        self.requested = []

    def get(self, reference):
        self.requested.append(reference)
        if self._failure is not None:
            raise self._failure
        if reference not in self._sizes:
            raise docker.errors.ImageNotFound(f"no such image: {reference}")
        return FakeImage(self._sizes[reference])

    def build(self, **kwargs):  # pragma: no cover — must never be called
        raise AssertionError("the Performance Analyzer must not build images")


class FakeClient:
    def __init__(self, sizes, failure=None):
        self.images = FakeImages(sizes, failure)
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def fake_docker(monkeypatch):
    """Install a fake client and hand the test a factory to configure it."""

    def install(sizes=None, failure=None):
        if sizes is None:
            sizes = {IMAGE_BEFORE: POC3_SIZE_BEFORE, IMAGE_AFTER: POC3_SIZE_AFTER}
        client = FakeClient(sizes, failure)
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
    assert SizeMetric.from_sizes(3_633_775, 3_634_192).delta_size == 417


def test_size_metric_delta_is_signed_after_minus_before():
    assert SizeMetric.from_sizes(100, 250).delta_size == 150
    assert SizeMetric.from_sizes(250, 100).delta_size == -150
    assert SizeMetric.from_sizes(100, 100).delta_size == 0


def test_size_metric_tolerates_a_zero_before_size():
    assert SizeMetric.from_sizes(0, 500).delta_size == 500


# --- Measurement ----------------------------------------------------------------


def test_measure_size_delta_returns_both_sizes_and_the_delta(fake_docker):
    fake_docker()
    metric = measure_size_delta(IMAGE_BEFORE, IMAGE_AFTER)
    assert metric.size_before == POC3_SIZE_BEFORE
    assert metric.size_after == POC3_SIZE_AFTER
    assert metric.delta_size == -26_318_550


def test_measurement_inspects_exactly_the_two_images_it_was_given(fake_docker):
    client = fake_docker()
    measure_size_delta(IMAGE_BEFORE, IMAGE_AFTER)
    assert client.images.requested == [IMAGE_BEFORE, IMAGE_AFTER]


def test_the_component_never_builds_anything(fake_docker):
    # Building belongs to the preparation phase; the fake asserts on any call.
    fake_docker()
    measure_size_delta(IMAGE_BEFORE, IMAGE_AFTER)


def test_the_component_leaves_both_images_in_place(fake_docker):
    # Removal is the preparation phase's responsibility: the Data Extractor
    # runs in parallel and needs the same images.
    client = fake_docker()
    measure_size_delta(IMAGE_BEFORE, IMAGE_AFTER)
    assert not hasattr(client.images, "removed")
    assert client.closed


# --- Exception contract (RNF4) --------------------------------------------------


def test_unreachable_daemon_raises_performance_analyzer_error(monkeypatch):
    def unavailable():
        raise docker.errors.DockerException("daemon not running")

    monkeypatch.setattr(docker, "from_env", unavailable)
    with pytest.raises(PerformanceAnalyzerError, match="Docker daemon"):
        measure_size_delta(IMAGE_BEFORE, IMAGE_AFTER)


def test_an_unknown_image_names_the_offending_state(fake_docker):
    fake_docker(sizes={IMAGE_BEFORE: POC3_SIZE_BEFORE})  # the after image is missing
    with pytest.raises(PerformanceAnalyzerError, match="'after'"):
        measure_size_delta(IMAGE_BEFORE, IMAGE_AFTER)


def test_api_error_during_inspection_raises_performance_analyzer_error(fake_docker):
    fake_docker(failure=docker.errors.APIError("daemon went away"))
    with pytest.raises(PerformanceAnalyzerError, match="daemon error"):
        measure_size_delta(IMAGE_BEFORE, IMAGE_AFTER)


def test_missing_size_attribute_raises_performance_analyzer_error(fake_docker):
    fake_docker(sizes={IMAGE_BEFORE: POC3_SIZE_BEFORE, IMAGE_AFTER: None})
    with pytest.raises(PerformanceAnalyzerError, match="inspect the size"):
        measure_size_delta(IMAGE_BEFORE, IMAGE_AFTER)


def test_non_integer_size_raises_performance_analyzer_error(fake_docker):
    # A string size is exactly what the rejected CLI path would deliver.
    fake_docker(sizes={IMAGE_BEFORE: POC3_SIZE_BEFORE, IMAGE_AFTER: "3.4MB"})
    with pytest.raises(PerformanceAnalyzerError, match="integer byte count"):
        measure_size_delta(IMAGE_BEFORE, IMAGE_AFTER)


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
    """RF4 end to end: the preparation phase builds, the analyzer measures."""
    before = "FROM alpine:3.20\nRUN echo before > /marker\n"
    after = "FROM alpine:3.20\nRUN echo after-with-more-content > /marker\n"

    with build_image_pair(before, after) as pair:
        metric = measure_size_delta(pair.image_before, pair.image_after)

    assert metric.size_before > 0 and metric.size_after > 0
    assert metric.delta_size == metric.size_after - metric.size_before
