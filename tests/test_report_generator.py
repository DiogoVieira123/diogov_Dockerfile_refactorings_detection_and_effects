"""Unit tests for the Report Generator (RF7, RNF5).

The component invokes no external tool; the only I/O is writing its three
artifacts, which the tests direct at pytest's tmp_path.
"""

import json
from datetime import datetime, timezone

import pytest

from src.data_extractor import ExtractionResult, MetricSet
from src.detection_engine import DetectionResult, Instruction
from src.performance_analyzer import SizeMetric
from src.report_generator import (
    HADOLINT_RAW_FILENAME,
    RAW_DATA_DIRNAME,
    REPORT_FILENAME,
    SUMMARY_FILENAME,
    TRIVY_RAW_FILENAME,
    ImpactReport,
    build_report,
    generate_report,
    to_json,
    to_text,
)

FIXED_MOMENT = datetime(2026, 8, 10, 14, 30, 0, tzinfo=timezone.utc)

TOOL_VERSIONS = {
    "docker_engine": "29.1.3",
    "hadolint": "Haskell Dockerfile Linter 2.14.0",
    "trivy": "0.72.0",
    "trivy_vulnerability_db": "2026-08-10T01:00:06Z",
    "dockerfile_parse": "2.0.1",
}

DETECTION = DetectionResult(
    refactoring_id="R09",
    refactoring_name="Extract RUN Instructions",
    instructions_before=(Instruction("RUN", "mkdir -p /app/data && cp a b"),),
    instructions_after=(
        Instruction("COPY", "setup.sh /app/setup.sh"),
        Instruction("RUN", "/app/setup.sh"),
    ),
)

RAW_TRIVY_BEFORE = '{"Results": [{"Vulnerabilities": [{"VulnerabilityID": "CVE-1"}]}]}'
RAW_TRIVY_AFTER = '{"Results": []}'
RAW_HADOLINT_BEFORE = '[{"code": "DL3007", "line": 1}]'
RAW_HADOLINT_AFTER = "[]"


def _extraction(
    cves_before=10,
    cves_after=4,
    warnings_before=3,
    warnings_after=1,
    instructions_before=5,
    instructions_after=6,
    severity_before=None,
    severity_after=None,
    raw_trivy=None,
    raw_hadolint=None,
):
    severity_before = severity_before or {
        "CRITICAL": 2, "HIGH": 3, "MEDIUM": 5, "LOW": 0, "UNKNOWN": 0
    }
    severity_after = severity_after or {
        "CRITICAL": 0, "HIGH": 1, "MEDIUM": 3, "LOW": 0, "UNKNOWN": 0
    }
    before = MetricSet(
        cves=cves_before,
        cves_by_severity=severity_before,
        warnings=warnings_before,
        instructions=instructions_before,
    )
    after = MetricSet(
        cves=cves_after,
        cves_by_severity=severity_after,
        warnings=warnings_after,
        instructions=instructions_after,
    )
    return ExtractionResult(
        before=before,
        after=after,
        delta_cves=after.cves - before.cves,
        delta_cves_by_severity={
            tier: severity_after[tier] - severity_before[tier] for tier in severity_before
        },
        delta_warnings=after.warnings - before.warnings,
        delta_logical_instructions=after.instructions - before.instructions,
        raw_trivy=raw_trivy
        or {"before": RAW_TRIVY_BEFORE, "after": RAW_TRIVY_AFTER},
        raw_hadolint=raw_hadolint
        or {"before": RAW_HADOLINT_BEFORE, "after": RAW_HADOLINT_AFTER},
    )


def _report(detections=(DETECTION,), size=None, extraction=None):
    return build_report(
        detections,
        size or SizeMetric.from_sizes(3_633_775, 3_634_192),
        extraction or _extraction(),
        repository="/repos/example",
        dockerfile_path="Dockerfile",
        commit_before="2bca273",
        commit_after="2981665",
        tool_versions=TOOL_VERSIONS,
        timestamp=FIXED_MOMENT,
    )


@pytest.fixture
def written(tmp_path):
    """Write the three artifacts into tmp_path and hand back the paths."""
    return generate_report(
        (DETECTION,),
        SizeMetric.from_sizes(3_633_775, 3_634_192),
        _extraction(),
        output_dir=tmp_path,
        repository="/repos/example",
        dockerfile_path="Dockerfile",
        commit_before="2bca273",
        commit_after="2981665",
        tool_versions=TOOL_VERSIONS,
        timestamp=FIXED_MOMENT,
    )


# --- RF7: the four deltas, under the chapter's key names ---------------------------


def test_the_report_carries_the_four_metric_deltas():
    metrics = _report().metrics
    assert metrics["size_bytes"]["delta_size"] == 417
    assert metrics["cves"]["delta_cves"] == -6
    assert metrics["warnings"]["delta_warnings"] == -2
    assert metrics["logical_instructions"]["delta_logical_instructions"] == 1


def test_the_delta_key_names_match_the_design_chapter():
    payload = json.loads(to_json(_report()))
    emitted = {
        key
        for block in payload["metrics"].values()
        if isinstance(block, dict)
        for key in block
        if key.startswith("delta_")
    }
    assert emitted == {
        "delta_size",
        "delta_cves",
        "delta_warnings",
        "delta_logical_instructions",
    }


def test_every_metric_carries_its_before_and_after_values():
    metrics = _report().metrics
    assert (metrics["size_bytes"]["before"], metrics["size_bytes"]["after"]) == (
        3_633_775,
        3_634_192,
    )
    assert (metrics["cves"]["before"], metrics["cves"]["after"]) == (10, 4)
    assert (metrics["warnings"]["before"], metrics["warnings"]["after"]) == (3, 1)
    assert (
        metrics["logical_instructions"]["before"],
        metrics["logical_instructions"]["after"],
    ) == (5, 6)


def test_deltas_are_taken_from_the_upstream_components_unaltered():
    extraction = _extraction()
    report = _report(extraction=extraction)
    assert report.metrics["cves"]["delta_cves"] == extraction.delta_cves
    assert report.metrics["warnings"]["delta_warnings"] == extraction.delta_warnings


# --- Aggregation, not interpretation ------------------------------------------------


def test_the_report_names_no_quality_dimension_and_passes_no_judgement():
    report = _report()
    serialised = to_json(report).lower().replace(
        report.metrics["sign_convention"].lower(), ""
    )
    for forbidden in (
        "performance",
        "security",
        "maintainability",
        "improvement",
        "degradation",
        "expected",
        "better",
        "worse",
    ):
        assert forbidden not in serialised


def test_the_identifier_travels_through_unchanged():
    entry = _report().refactorings[0]
    assert entry["refactoring_id"] == "R09"
    assert entry["refactoring_name"] == "Extract RUN Instructions"


def test_the_instructions_involved_are_reported_with_named_fields():
    entry = _report().refactorings[0]
    assert entry["instructions_before"] == [
        {"instruction": "RUN", "value": "mkdir -p /app/data && cp a b"}
    ]
    assert entry["instructions_after"][0] == {
        "instruction": "COPY",
        "value": "setup.sh /app/setup.sh",
    }


def test_multiple_detections_are_reported_in_the_order_received():
    second = DetectionResult("R11", "Move Stage", (), ())
    report = _report(detections=(DETECTION, second))
    assert [e["refactoring_id"] for e in report.refactorings] == ["R09", "R11"]


def test_no_detection_is_a_valid_report_and_not_a_failure():
    report = _report(detections=())
    assert report.refactorings == []
    assert report.metrics["size_bytes"]["delta_size"] == 417
    assert "None." in to_text(report)


# --- Absolute figures only -------------------------------------------------------------


def test_every_metric_block_holds_only_absolute_figures():
    metrics = _report().metrics
    for key, delta_key in (
        ("size_bytes", "delta_size"),
        ("cves", "delta_cves"),
        ("warnings", "delta_warnings"),
        ("logical_instructions", "delta_logical_instructions"),
    ):
        assert set(metrics[key]) >= {"before", "after", delta_key}
        assert "delta_percent" not in metrics[key]


def test_no_relative_figure_appears_in_either_format():
    report = _report()
    assert "percent" not in to_json(report)
    assert "%" not in to_text(report)


# --- CVE severity vector ---------------------------------------------------------------


def test_the_severity_vector_reports_net_change_per_tier():
    by_severity = _report().metrics["cves"]["by_severity"]
    assert by_severity["before"]["CRITICAL"] == 2
    assert by_severity["after"]["CRITICAL"] == 0
    assert by_severity["delta"] == {
        "CRITICAL": -2, "HIGH": -2, "MEDIUM": -2, "LOW": 0, "UNKNOWN": 0
    }


def test_the_severity_vector_covers_every_tier():
    delta = _report().metrics["cves"]["by_severity"]["delta"]
    assert set(delta) == {"CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"}


def test_a_worsening_distribution_is_visible_behind_an_improving_total():
    report = _report(
        extraction=_extraction(
            cves_before=10,
            cves_after=6,
            severity_before={"CRITICAL": 0, "HIGH": 2, "MEDIUM": 8, "LOW": 0, "UNKNOWN": 0},
            severity_after={"CRITICAL": 3, "HIGH": 1, "MEDIUM": 2, "LOW": 0, "UNKNOWN": 0},
        )
    )
    assert report.metrics["cves"]["delta_cves"] == -4
    assert report.metrics["cves"]["by_severity"]["delta"]["CRITICAL"] == +3
    assert "CRITICAL" in to_text(report)


# --- RNF5: reproducibility ------------------------------------------------------------


def test_the_report_records_the_timestamp_and_both_commit_shas():
    analysis = _report().analysis
    assert analysis["timestamp_utc"] == "2026-08-10 14:30:00 UTC"
    assert analysis["commit_before"] == "2bca273"
    assert analysis["commit_after"] == "2981665"


def test_the_report_records_the_tracked_dockerfile_path():
    assert _report().analysis["dockerfile_path"] == "Dockerfile"


def test_the_report_records_every_tool_version_including_the_trivy_database():
    environment = _report().environment
    assert environment["docker_engine"] == "29.1.3"
    assert environment["hadolint"].startswith("Haskell Dockerfile Linter")
    assert environment["trivy"] == "0.72.0"
    assert environment["trivy_vulnerability_db"] == "2026-08-10T01:00:06Z"
    assert environment["dockerfile_parse"] == "2.0.1"


def test_the_tool_versions_are_copied_and_not_aliased():
    versions = dict(TOOL_VERSIONS)
    report = _report()
    versions["trivy"] = "tampered"
    assert report.environment["trivy"] == "0.72.0"


def test_the_timestamp_defaults_to_now_when_not_supplied():
    report = build_report(
        (),
        SizeMetric.from_sizes(1, 2),
        _extraction(),
        repository="/r",
        dockerfile_path="Dockerfile",
        commit_before="a",
        commit_after="b",
        tool_versions={},
    )
    assert report.analysis["timestamp_utc"].endswith("UTC")


# --- Serialisation ---------------------------------------------------------------------


def test_the_json_is_valid_and_carries_every_section():
    payload = json.loads(to_json(_report()))
    assert set(payload) == {
        "analysis",
        "refactorings_detected",
        "metrics",
        "environment",
        "raw_data",
    }


def test_the_json_states_the_sign_convention():
    convention = json.loads(to_json(_report()))["metrics"]["sign_convention"]
    assert "after - before" in convention
    assert "not monotonic" in convention


def test_the_text_summary_carries_the_same_values_as_the_json():
    text = to_text(_report())
    assert "R09" in text and "Extract RUN Instructions" in text
    assert "2bca273" in text and "2981665" in text
    assert "+417" in text
    assert "-6" in text
    assert "29.1.3" in text


def test_the_text_summary_is_derived_and_never_recomputes_a_value():
    report = _report()
    report.metrics["size_bytes"]["delta_size"] = 999_999
    assert "+999,999" in to_text(report)


def test_an_impact_report_is_the_declared_structure():
    assert isinstance(_report(), ImpactReport)
    assert ImpactReport._fields == (
        "analysis",
        "refactorings",
        "metrics",
        "environment",
        "raw_data",
    )


# --- The three written artifacts --------------------------------------------------------


def test_the_three_artifacts_are_written(written, tmp_path):
    assert written.report_json == tmp_path / REPORT_FILENAME
    assert written.summary_text == tmp_path / SUMMARY_FILENAME
    assert written.raw_data_dir == tmp_path / RAW_DATA_DIRNAME
    assert written.report_json.is_file()
    assert written.summary_text.is_file()
    assert written.raw_data_dir.is_dir()


def test_the_written_json_parses_and_matches_the_in_memory_report(written):
    payload = json.loads(written.report_json.read_text(encoding="utf-8"))
    assert payload["metrics"]["size_bytes"]["delta_size"] == 417
    assert payload["analysis"]["timestamp_utc"] == "2026-08-10 14:30:00 UTC"


def test_the_raw_data_directory_holds_one_file_per_tool(written):
    names = {entry.name for entry in written.raw_data_dir.iterdir()}
    assert names == {TRIVY_RAW_FILENAME, HADOLINT_RAW_FILENAME}


def test_the_raw_artifacts_keep_both_states_distinguishable(written):
    trivy = json.loads(
        (written.raw_data_dir / TRIVY_RAW_FILENAME).read_text(encoding="utf-8")
    )
    hadolint = json.loads(
        (written.raw_data_dir / HADOLINT_RAW_FILENAME).read_text(encoding="utf-8")
    )
    assert set(trivy) == {"before", "after"}
    assert set(hadolint) == {"before", "after"}


def test_the_raw_artifacts_hold_the_findings_that_produced_the_counts(written):
    trivy = json.loads(
        (written.raw_data_dir / TRIVY_RAW_FILENAME).read_text(encoding="utf-8")
    )
    hadolint = json.loads(
        (written.raw_data_dir / HADOLINT_RAW_FILENAME).read_text(encoding="utf-8")
    )
    assert trivy["before"]["Results"][0]["Vulnerabilities"][0]["VulnerabilityID"] == "CVE-1"
    assert hadolint["before"][0]["code"] == "DL3007"
    assert hadolint["after"] == []


def test_output_that_is_not_json_is_kept_rather_than_discarded(tmp_path):
    # A tool emitting something unexpected must not cost us the evidence.
    artifacts = generate_report(
        (),
        SizeMetric.from_sizes(1, 2),
        _extraction(raw_trivy={"before": "not json at all", "after": "{}"}),
        output_dir=tmp_path,
        repository="/r",
        dockerfile_path="Dockerfile",
        commit_before="a",
        commit_after="b",
        tool_versions={},
    )
    trivy = json.loads(
        (artifacts.raw_data_dir / TRIVY_RAW_FILENAME).read_text(encoding="utf-8")
    )
    assert trivy["before"] == "not json at all"


def test_the_json_points_at_the_raw_data_files(written):
    payload = json.loads(written.report_json.read_text(encoding="utf-8"))
    assert payload["raw_data"]["trivy"] == f"{RAW_DATA_DIRNAME}/{TRIVY_RAW_FILENAME}"
    assert payload["raw_data"]["hadolint"] == f"{RAW_DATA_DIRNAME}/{HADOLINT_RAW_FILENAME}"


def test_the_summary_names_the_retained_artifacts(written):
    summary = written.summary_text.read_text(encoding="utf-8")
    assert TRIVY_RAW_FILENAME in summary and HADOLINT_RAW_FILENAME in summary


def test_the_output_directory_is_created_when_absent(tmp_path):
    target = tmp_path / "nested" / "run-001"
    artifacts = generate_report(
        (),
        SizeMetric.from_sizes(1, 2),
        _extraction(),
        output_dir=target,
        repository="/r",
        dockerfile_path="Dockerfile",
        commit_before="a",
        commit_after="b",
        tool_versions={},
    )
    assert artifacts.report_json.is_file()


def test_the_artifacts_are_written_with_lf_endings(written):
    # A report produced on Windows must be byte-identical to one produced on
    # Linux, so a re-run can be compared with diff.
    assert b"\r\n" not in written.report_json.read_bytes()
    assert b"\r\n" not in written.summary_text.read_bytes()


# --- End to end over the real upstream structures ----------------------------------------


def test_report_built_from_genuine_detection_engine_output(tmp_path):
    """The identifier and instructions arrive from a real detection."""
    from src.detection_engine import detect_refactorings

    before = "FROM alpine:3.20\nRUN echo a\nRUN echo b\n"
    after = "FROM alpine:3.20\nRUN echo a && echo b\n"
    detections = detect_refactorings(before, after)
    assert detections, "the fixture pair must produce a detection"

    artifacts = generate_report(
        detections,
        SizeMetric.from_sizes(100, 90),
        _extraction(),
        output_dir=tmp_path,
        repository="/r",
        dockerfile_path="Dockerfile",
        commit_before="a",
        commit_after="b",
        tool_versions=TOOL_VERSIONS,
    )
    payload = json.loads(artifacts.report_json.read_text(encoding="utf-8"))
    assert [e["refactoring_id"] for e in payload["refactorings_detected"]] == [
        d.refactoring_id for d in detections
    ]
