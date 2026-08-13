"""Tests for the pipeline orchestrator and the command-line entry point.

The five components are replaced by fakes, so these tests exercise the wiring —
the order of the stages, the concurrency of Stage 2, the lifetime of the built
images and the mapping of each failure to its exit code — without a daemon and
without repeating what each component's own suite already covers.
"""

import contextlib
import json
import shutil
import tempfile
from pathlib import Path

import pytest

import main as cli
from src import pipeline
from src.data_extractor import DataExtractorError, ExtractionResult, MetricSet
from src.detection_engine import DetectionResult, DockerfileParseError
from src.image_builder import ImageBuildError
from src.performance_analyzer import PerformanceAnalyzerError, SizeMetric
from src.vcs_connector import CommitNotFoundError, DockerfilePair

DETECTION = DetectionResult("R09", "Extract RUN Instructions", (), ())
SEVERITY = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}


def _extraction():
    state = MetricSet(cves=0, cves_by_severity=SEVERITY, warnings=0, instructions=5)
    after = MetricSet(cves=0, cves_by_severity=SEVERITY, warnings=0, instructions=6)
    return ExtractionResult(
        before=state,
        after=after,
        delta_cves=0,
        delta_cves_by_severity=SEVERITY,
        delta_warnings=0,
        delta_logical_instructions=1,
        raw_hadolint={"before": "[]", "after": "[]"},
        raw_trivy={"before": "{}", "after": "{}"},
    )


class Recorder:
    """Records the order in which the pipeline drove its components."""

    def __init__(self):
        self.calls = []
        self.images_alive_during_stage_2 = None


@pytest.fixture
def wired(monkeypatch):
    """Replace every component with a fake and record the sequence."""
    log = Recorder()
    state = {"images_open": False}

    def retrieve(repo, sha_a, sha_b, dockerfile_path="Dockerfile"):
        log.calls.append(("retrieve", repo, sha_a, sha_b, dockerfile_path))
        return DockerfilePair("FROM alpine:3.20\n", "FROM alpine:3.20\nENV A=1\n")

    def detect(a, b):
        log.calls.append(("detect",))
        return [DETECTION]

    @contextlib.contextmanager
    def export(repository, sha):
        log.calls.append(("export", str(repository), sha))
        directory = tempfile.mkdtemp(prefix=f"fake-tree-{sha}-")
        state.setdefault("trees", []).append(Path(directory))
        try:
            yield Path(directory)
        finally:
            log.calls.append(("tree_removed", sha))
            shutil.rmtree(directory, ignore_errors=True)

    @contextlib.contextmanager
    def build(before, after, context_before=None, context_after=None):
        log.calls.append(("build", str(context_before), str(context_after)))
        state["images_open"] = True
        try:
            yield type("Pair", (), {"image_before": "img-a", "image_after": "img-b"})()
        finally:
            state["images_open"] = False
            log.calls.append(("images_removed",))

    def measure(image_before, image_after):
        log.calls.append(("measure", image_before, image_after))
        log.images_alive_during_stage_2 = state["images_open"]
        return SizeMetric.from_sizes(100, 120)

    def extract(a, b, image_before, image_after):
        log.calls.append(("extract", image_before, image_after))
        return _extraction()

    monkeypatch.setattr(pipeline, "retrieve_dockerfile_pair", retrieve)
    monkeypatch.setattr(pipeline, "detect_refactorings", detect)
    monkeypatch.setattr(pipeline, "commit_context", export)
    monkeypatch.setattr(pipeline, "build_image_pair", build)
    monkeypatch.setattr(pipeline, "measure_size_delta", measure)
    monkeypatch.setattr(pipeline, "extract_metrics", extract)
    monkeypatch.setattr(pipeline, "_collect_tool_versions", lambda: {"docker_engine": "29.1.3"})
    return log


# --- commit_context: exporting a historical file tree ------------------------------


@pytest.fixture
def two_commit_repo(tmp_path):
    """A repository whose two commits differ in the files, not only the text."""
    import git

    root = tmp_path / "repo"
    root.mkdir()
    repo = git.Repo.init(root)
    with repo.config_writer() as config:
        config.set_value("user", "email", "t@t.t")
        config.set_value("user", "name", "tester")

    (root / "Dockerfile").write_text("FROM alpine:3.20\nCOPY app.txt /\n", encoding="utf-8")
    (root / "app.txt").write_text("first version\n", encoding="utf-8")
    repo.index.add(["Dockerfile", "app.txt"])
    first = repo.index.commit("before")

    (root / "app.txt").write_text("second version, longer\n", encoding="utf-8")
    (root / "extra.txt").write_text("added later\n", encoding="utf-8")
    repo.index.add(["app.txt", "extra.txt"])
    second = repo.index.commit("after")

    # The working tree now holds the later state; the export must not.
    return root, first.hexsha, second.hexsha


def test_commit_context_exports_the_tree_as_it_was_at_that_commit(two_commit_repo):
    root, first, second = two_commit_repo
    with pipeline.commit_context(root, first) as tree:
        assert (tree / "app.txt").read_text(encoding="utf-8") == "first version\n"
        # A file added only in the later commit must be absent.
        assert not (tree / "extra.txt").exists()

    with pipeline.commit_context(root, second) as tree:
        assert (tree / "app.txt").read_text(encoding="utf-8") == "second version, longer\n"
        assert (tree / "extra.txt").exists()


def test_commit_context_removes_the_directory_on_exit(two_commit_repo):
    root, first, _ = two_commit_repo
    with pipeline.commit_context(root, first) as tree:
        exported = tree
        assert exported.is_dir()
    assert not exported.exists()


def test_commit_context_removes_the_directory_when_the_caller_raises(two_commit_repo):
    root, first, _ = two_commit_repo
    exported = None
    with pytest.raises(ValueError):
        with pipeline.commit_context(root, first) as tree:
            exported = tree
            raise ValueError("caller failed")
    assert exported is not None and not exported.exists()


def test_commit_context_leaves_the_working_tree_untouched(two_commit_repo):
    # RF1: nothing is checked out; the repository is left as it was found.
    root, first, _ = two_commit_repo
    before = (root / "app.txt").read_text(encoding="utf-8")
    with pipeline.commit_context(root, first):
        pass
    assert (root / "app.txt").read_text(encoding="utf-8") == before
    assert (root / "extra.txt").exists()


def test_commit_context_accepts_an_abbreviated_sha(two_commit_repo):
    root, first, _ = two_commit_repo
    with pipeline.commit_context(root, first[:7]) as tree:
        assert (tree / "Dockerfile").is_file()


def test_commit_context_rejects_an_unknown_commit(two_commit_repo):
    root, _, _ = two_commit_repo
    with pytest.raises(pipeline.CommitContextError, match="export the file tree"):
        with pipeline.commit_context(root, "0" * 40):
            pass


def test_commit_context_rejects_a_path_that_is_not_a_repository(tmp_path):
    with pytest.raises(pipeline.CommitContextError, match="Could not open"):
        with pipeline.commit_context(tmp_path / "nowhere", "HEAD"):
            pass


# --- Stage sequencing -------------------------------------------------------------


def test_the_pipeline_runs_the_stages_in_order(wired, tmp_path):
    pipeline.run_analysis("/repo", "aaa", "bbb", tmp_path)
    order = [call[0] for call in wired.calls]
    assert order.index("retrieve") < order.index("detect")
    assert order.index("detect") < order.index("build")
    assert order.index("build") < order.index("measure")
    assert order.index("build") < order.index("extract")
    # Teardown unwinds in reverse: the images go first, then the commit trees
    # that were exported to build them.
    assert order.index("images_removed") < order.index("tree_removed")
    assert order[-1] == "tree_removed"


def test_both_stage_2_components_receive_the_same_images(wired, tmp_path):
    pipeline.run_analysis("/repo", "aaa", "bbb", tmp_path)
    measure = next(c for c in wired.calls if c[0] == "measure")
    extract = next(c for c in wired.calls if c[0] == "extract")
    assert measure[1:] == ("img-a", "img-b")
    assert extract[1:] == ("img-a", "img-b")


def test_the_images_are_still_alive_while_stage_2_runs(wired, tmp_path):
    pipeline.run_analysis("/repo", "aaa", "bbb", tmp_path)
    assert wired.images_alive_during_stage_2 is True


def test_the_images_are_removed_after_the_analysis(wired, tmp_path):
    pipeline.run_analysis("/repo", "aaa", "bbb", tmp_path)
    assert ("images_removed",) in wired.calls


def test_the_tracked_dockerfile_path_reaches_the_vcs_connector(wired, tmp_path):
    pipeline.run_analysis(
        "/repo", "aaa", "bbb", tmp_path, dockerfile_path="docker/Dockerfile"
    )
    assert wired.calls[0][4] == "docker/Dockerfile"


def test_each_state_is_built_from_its_own_commit_tree(wired, tmp_path):
    # The point of the historical export: the two builds must not share a
    # context, or a file that changed alongside the refactoring would reach
    # both measurements.
    pipeline.run_analysis("/repo", "aaa", "bbb", tmp_path)
    exports = [c for c in wired.calls if c[0] == "export"]
    assert [c[2] for c in exports] == ["aaa", "bbb"]

    build = next(c for c in wired.calls if c[0] == "build")
    context_before, context_after = build[1], build[2]
    assert context_before != context_after
    assert "aaa" in context_before and "bbb" in context_after


def test_the_commit_trees_are_exported_from_the_given_repository(wired, tmp_path):
    pipeline.run_analysis("/repo", "aaa", "bbb", tmp_path)
    exports = [c for c in wired.calls if c[0] == "export"]
    assert all(Path(c[1]) == Path("/repo") for c in exports)


def test_the_trees_exist_during_the_build_and_are_removed_after(wired, tmp_path):
    pipeline.run_analysis("/repo", "aaa", "bbb", tmp_path)
    order = [c[0] for c in wired.calls]
    # Both exports precede the build, and both removals follow it.
    assert order.index("export") < order.index("build")
    assert order.index("images_removed") < order.index("tree_removed")
    assert len([c for c in wired.calls if c[0] == "tree_removed"]) == 2


def test_the_trees_are_removed_even_when_a_stage_fails(wired, tmp_path, monkeypatch):
    def failing(image_before, image_after):
        raise PerformanceAnalyzerError("no size")

    monkeypatch.setattr(pipeline, "measure_size_delta", failing)
    with pytest.raises(PerformanceAnalyzerError):
        pipeline.run_analysis("/repo", "aaa", "bbb", tmp_path)
    assert len([c for c in wired.calls if c[0] == "tree_removed"]) == 2


# --- Output ------------------------------------------------------------------------


def test_the_analysis_writes_the_three_artifacts(wired, tmp_path):
    artifacts = pipeline.run_analysis("/repo", "aaa", "bbb", tmp_path)
    assert artifacts.report_json.is_file()
    assert artifacts.summary_text.is_file()
    assert artifacts.raw_data_dir.is_dir()


def test_the_report_carries_the_detection_and_the_commits(wired, tmp_path):
    artifacts = pipeline.run_analysis("/repo", "aaa", "bbb", tmp_path)
    payload = json.loads(artifacts.report_json.read_text(encoding="utf-8"))
    assert payload["refactorings_detected"][0]["refactoring_id"] == "R09"
    assert payload["analysis"]["commit_before"] == "aaa"
    assert payload["analysis"]["commit_after"] == "bbb"
    assert payload["environment"]["docker_engine"] == "29.1.3"


# --- Failure propagation ------------------------------------------------------------


def test_a_stage_2_failure_still_removes_the_images(wired, tmp_path, monkeypatch):
    def failing(image_before, image_after):
        raise PerformanceAnalyzerError("no size")

    monkeypatch.setattr(pipeline, "measure_size_delta", failing)
    with pytest.raises(PerformanceAnalyzerError):
        pipeline.run_analysis("/repo", "aaa", "bbb", tmp_path)
    assert ("images_removed",) in wired.calls


def test_a_data_extractor_failure_propagates(wired, tmp_path, monkeypatch):
    def failing(a, b, image_before, image_after):
        raise DataExtractorError("trivy down")

    monkeypatch.setattr(pipeline, "extract_metrics", failing)
    with pytest.raises(DataExtractorError):
        pipeline.run_analysis("/repo", "aaa", "bbb", tmp_path)


def test_no_image_is_built_when_retrieval_fails(wired, tmp_path, monkeypatch):
    def failing(repo, sha_a, sha_b, dockerfile_path="Dockerfile"):
        raise CommitNotFoundError("no such commit")

    monkeypatch.setattr(pipeline, "retrieve_dockerfile_pair", failing)
    with pytest.raises(CommitNotFoundError):
        pipeline.run_analysis("/repo", "aaa", "bbb", tmp_path)
    assert not any(call[0] == "build" for call in wired.calls)


# --- Command-line entry point --------------------------------------------------------


def test_the_cli_returns_zero_and_prints_the_summary(wired, tmp_path, capsys):
    code = cli.main(["/repo", "aaa", "bbb", "-o", str(tmp_path)])
    assert code == cli.EXIT_OK
    output = capsys.readouterr().out
    assert "Dockerfile Refactoring Impact Report" in output
    assert "R09" in output


@pytest.mark.parametrize(
    "exception, expected_code",
    [
        (CommitNotFoundError("x"), cli.EXIT_VCS),
        (DockerfileParseError("x"), cli.EXIT_PARSE),
        (ImageBuildError("x"), cli.EXIT_BUILD),
        (PerformanceAnalyzerError("x"), cli.EXIT_SIZE),
        (DataExtractorError("x"), cli.EXIT_EXTRACT),
    ],
    ids=["vcs", "parse", "build", "size", "extract"],
)
def test_each_failure_maps_to_its_own_exit_code(
    monkeypatch, tmp_path, capsys, exception, expected_code
):
    # RNF4 asks for distinct informative exceptions; the exit code is what keeps
    # them distinguishable once the process has ended.
    def failing(*args, **kwargs):
        raise exception

    monkeypatch.setattr(cli, "run_analysis", failing)
    assert cli.main(["/repo", "aaa", "bbb", "-o", str(tmp_path)]) == expected_code
    assert "Analysis failed" in capsys.readouterr().err


def test_the_cli_accepts_a_dockerfile_path(monkeypatch, tmp_path):
    captured = {}

    def spy(repo, before, after, output, *, dockerfile_path):
        captured.update(dockerfile_path=dockerfile_path)
        raise ImageBuildError("stop here")

    monkeypatch.setattr(cli, "run_analysis", spy)
    cli.main(["/repo", "a", "b", "-o", str(tmp_path), "-d", "sub/Dockerfile"])
    assert captured == {"dockerfile_path": "sub/Dockerfile"}
