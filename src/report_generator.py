"""Report Generator — Stage 4, the terminal stage (Chapter 5, Section 5.7).

Consumes the DetectionResult list produced by the Detection Engine and the
metrics produced by the two Stage 3 components, and writes the ImpactReport as
three artifacts on disk (RF7, RNF5):

* ``impact_report.json`` — the structured output, carrying the before and after
  value of every metric, the four deltas, the per-severity CVE vector, and the
  reproducibility block;
* ``raw_data/`` — the source analysis artifacts the Data Extractor retained,
  written as ``trivy_raw.json`` and ``hadolint_raw.json`` so a counted metric
  can be traced back to the finding that produced it;
* ``human_readable_summary.txt`` — the same content arranged for direct review.

Its role is aggregation, not interpretation. It pairs the formal catalogue
identifier of each detected refactoring with the four measured deltas exactly
as they were obtained, and adds no expected direction, no dimensional label and
no judgement about whether a result matches the catalogue. Nothing here reads
the extended catalogue: the identifier arrives as a label attached to the
detection and leaves as the same label (RF3).

Two reading conventions are recorded in the report itself rather than applied
to the numbers:

* For size, CVEs and warnings the sign is uniform — a negative delta is an
  improvement — so the report states the convention and leaves the numbers
  untouched.
* ΔInstr is not monotonic. Consolidation and removal reduce it while extraction
  and addition increase it, so a positive value is not a degradation on its
  own. The report presents it next to the refactoring identifiers that produced
  it and states that it must be read against the operation applied, which is
  the whole of the contextual reading this stage is permitted to supply.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Mapping, NamedTuple, Optional, Sequence, Union

# File names of the three artifacts, fixed so a consumer can find them without
# being told where they are.
REPORT_FILENAME = "impact_report.json"
SUMMARY_FILENAME = "human_readable_summary.txt"
RAW_DATA_DIRNAME = "raw_data"
TRIVY_RAW_FILENAME = "trivy_raw.json"
HADOLINT_RAW_FILENAME = "hadolint_raw.json"

# Sign convention, recorded in the report so the reader does not have to infer
# it. Stated once here and emitted verbatim; it is a note, not a computation.
_SIGN_CONVENTION = (
    "delta = after - before. For size, CVEs and warnings a negative delta is "
    "an improvement. Delta of logical instructions is not monotonic: "
    "consolidation and removal reduce it while extraction and addition "
    "increase it, so its sign must be read against the refactoring that "
    "produced it."
)


class ImpactReport(NamedTuple):
    """The aggregated result of one analysis (RF7).

    Held as plain nested dictionaries rather than typed sub-structures because
    this is the pipeline's output boundary: the content is about to become JSON
    and its shape is the report's contract with whatever consumes it.
    """

    analysis: Dict  # timestamp, repository, Dockerfile path, both commit SHAs
    refactorings: list  # one entry per DetectionResult, in registry order
    metrics: Dict  # before, after and delta for each of the four metrics
    environment: Dict  # tool versions, for reproducibility (RNF5)
    raw_data: Dict  # source analysis artifacts, keyed by tool then by state


class ReportArtifacts(NamedTuple):
    """Where the three artifacts were written."""

    report_json: Path
    summary_text: Path
    raw_data_dir: Path


def _metric_block(before: int, after: int, delta_key: str, delta: int) -> Dict:
    """One metric's before value, after value and delta, named per RF7.

    Every figure is absolute. The four metrics are counts and byte totals, and
    reporting them in one form keeps them comparable with each other and with
    the recorded catalogue values, which are themselves absolute.
    """
    return {
        "before": before,
        "after": after,
        delta_key: delta,
    }


def _instruction_pairs(instructions: Sequence) -> list:
    """Instructions of a DetectionResult as JSON-serialisable pairs.

    Naming the fields keeps the report readable without the reader
    consulting the source, and states the two the report carries: an
    Instruction also records the typography R13 reads, which is evidence for
    a rule and not a property of the instruction worth publishing.
    """
    return [
        {"instruction": entry.instruction, "value": entry.value}
        for entry in instructions
    ]


def build_report(
    detections: Sequence,
    size_metric,
    extraction,
    *,
    repository: str,
    dockerfile_path: str,
    commit_before: str,
    commit_after: str,
    tool_versions: Mapping[str, str],
    timestamp: Optional[datetime] = None,
) -> ImpactReport:
    """Aggregate the detections and the measured metrics into an ImpactReport.

    Args:
        detections: the DetectionResult list from the Detection Engine, in rule
            registry order. An empty list is a valid analysis: it means no
            supported refactoring was recognised, not that the run failed.
        size_metric: the SizeMetric from the Performance Analyzer.
        extraction: the ExtractionResult from the Data Extractor.
        repository: path of the analysed repository.
        dockerfile_path: the single Dockerfile path tracked through both
            commits (RF1).
        commit_before: SHA of the earlier commit.
        commit_after: SHA of the later commit.
        tool_versions: version string per external tool, recorded verbatim
            (RNF5). Expected keys are docker_engine, hadolint, trivy,
            trivy_vulnerability_db and dockerfile_parse, but the mapping is
            copied as given so a caller may record more.
        timestamp: analysis time; defaults to now in UTC. Injectable so a test
            can assert on a fixed value.

    Returns:
        The ImpactReport, ready to write with :func:`generate_report` or to
        render with :func:`to_json` and :func:`to_text`.
    """
    moment = timestamp or datetime.now(timezone.utc)

    analysis = {
        "timestamp_utc": moment.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "repository": repository,
        "dockerfile_path": dockerfile_path,
        "commit_before": commit_before,
        "commit_after": commit_after,
    }

    refactorings = [
        {
            "refactoring_id": detection.refactoring_id,
            "refactoring_name": detection.refactoring_name,
            "instructions_before": _instruction_pairs(detection.instructions_before),
            "instructions_after": _instruction_pairs(detection.instructions_after),
        }
        for detection in detections
    ]

    metrics = {
        "size_bytes": _metric_block(
            size_metric.size_before,
            size_metric.size_after,
            "delta_size",
            size_metric.delta_size,
        ),
        "cves": _metric_block(
            extraction.before.cves,
            extraction.after.cves,
            "delta_cves",
            extraction.delta_cves,
        ),
        "warnings": _metric_block(
            extraction.before.warnings,
            extraction.after.warnings,
            "delta_warnings",
            extraction.delta_warnings,
        ),
        "logical_instructions": _metric_block(
            extraction.before.instructions,
            extraction.after.instructions,
            "delta_logical_instructions",
            extraction.delta_logical_instructions,
        ),
    }

    # The per-severity vector is a net change per tier rather than a single
    # aggregate, so a run whose total CVE count improves while its severity
    # distribution worsens is visible in the report instead of being averaged
    # away by the total.
    metrics["cves"]["by_severity"] = {
        "before": dict(extraction.before.cves_by_severity),
        "after": dict(extraction.after.cves_by_severity),
        "delta": dict(extraction.delta_cves_by_severity),
    }

    metrics["sign_convention"] = _SIGN_CONVENTION

    return ImpactReport(
        analysis=analysis,
        refactorings=refactorings,
        metrics=metrics,
        environment=dict(tool_versions),
        raw_data={
            "trivy": dict(extraction.raw_trivy),
            "hadolint": dict(extraction.raw_hadolint),
        },
    )


def to_json(report: ImpactReport, *, indent: int = 2) -> str:
    """Serialise the report as JSON (RF7).

    JSON is the primary format because it is a standardised representation for
    structured data, which is what makes the report consumable by downstream
    processing rather than only by a reader.

    The retained artifacts are not embedded here: they are written beside the
    report under ``raw_data/`` and referenced by name, so the structured output
    stays readable while the evidence remains one directory away.
    """
    return json.dumps(
        {
            "analysis": report.analysis,
            "refactorings_detected": report.refactorings,
            "metrics": report.metrics,
            "environment": report.environment,
            "raw_data": {
                "directory": RAW_DATA_DIRNAME,
                "trivy": f"{RAW_DATA_DIRNAME}/{TRIVY_RAW_FILENAME}",
                "hadolint": f"{RAW_DATA_DIRNAME}/{HADOLINT_RAW_FILENAME}",
            },
        },
        indent=indent,
        ensure_ascii=False,
    )


def to_text(report: ImpactReport) -> str:
    """Render the report as a human-readable summary (RF7).

    The same content as the JSON, arranged for direct review. No value is
    recomputed here: the summary reads the report's own fields, so the two
    formats cannot drift apart.
    """
    analysis = report.analysis
    lines = [
        "=" * 78,
        "  Dockerfile Refactoring Impact Report",
        "=" * 78,
        f"  Analysed        : {analysis['timestamp_utc']}",
        f"  Repository      : {analysis['repository']}",
        f"  Dockerfile      : {analysis['dockerfile_path']}",
        f"  Commits         : {analysis['commit_before']} -> {analysis['commit_after']}",
        "",
        "-" * 78,
        "  Refactorings detected",
        "-" * 78,
    ]

    if not report.refactorings:
        lines.append("  None. No supported refactoring was recognised between the")
        lines.append("  two states; the metrics below still describe the change.")
    else:
        for entry in report.refactorings:
            lines.append(f"  {entry['refactoring_id']}  {entry['refactoring_name']}")

    lines += [
        "",
        "-" * 78,
        "  Measured impact",
        "-" * 78,
        f"  {'Metric':<24}{'Before':>16}{'After':>16}{'Delta':>16}",
    ]

    rows = (
        ("Image size (bytes)", "size_bytes", "delta_size"),
        ("CVEs (distinct)", "cves", "delta_cves"),
        ("Warnings (47-rule)", "warnings", "delta_warnings"),
        ("Logical instructions", "logical_instructions", "delta_logical_instructions"),
    )
    for label, key, delta_key in rows:
        block = report.metrics[key]
        delta = f"{block[delta_key]:+,}"
        lines.append(
            f"  {label:<24}{block['before']:>16,}{block['after']:>16,}{delta:>16}"
        )

    severity = report.metrics["cves"]["by_severity"]["delta"]
    if any(severity.values()):
        lines += ["", "  CVE net change by severity"]
        for tier, value in severity.items():
            lines.append(f"    {tier:<12}{value:+d}")

    lines += [
        "",
        "-" * 78,
        "  Reading convention",
        "-" * 78,
    ]
    lines += [f"  {line}" for line in _wrap(report.metrics["sign_convention"], 74)]

    lines += [
        "",
        "-" * 78,
        "  Environment",
        "-" * 78,
    ]
    for tool, version in report.environment.items():
        lines.append(f"  {tool:<24}{version}")

    lines += [
        "",
        "-" * 78,
        "  Retained source analysis artifacts",
        "-" * 78,
        f"  {RAW_DATA_DIRNAME}/{TRIVY_RAW_FILENAME}",
        f"  {RAW_DATA_DIRNAME}/{HADOLINT_RAW_FILENAME}",
        "=" * 78,
    ]
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list:
    """Break a sentence into lines of at most ``width`` characters."""
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def generate_report(
    detections: Sequence,
    size_metric,
    extraction,
    *,
    output_dir: Union[str, Path],
    repository: str,
    dockerfile_path: str,
    commit_before: str,
    commit_after: str,
    tool_versions: Mapping[str, str],
    timestamp: Optional[datetime] = None,
) -> ReportArtifacts:
    """Write the three report artifacts to ``output_dir`` (RF7, RNF5).

    The component's entry point. Creates the directory and the ``raw_data``
    subdirectory if they do not exist, and writes:

    * ``impact_report.json`` — the structured output;
    * ``raw_data/trivy_raw.json`` and ``raw_data/hadolint_raw.json`` — the
      artifacts the Data Extractor retained, each keyed by state so the before
      and after evidence stay distinguishable;
    * ``human_readable_summary.txt`` — the readable summary.

    Every file is written as UTF-8 with LF endings, so an artifact produced on
    Windows is byte-identical to one produced on Linux and a re-run can be
    compared with `diff`.

    Args:
        output_dir: directory to write into; created if absent.
        (remaining arguments as in :func:`build_report`)

    Returns:
        The paths of the three artifacts.
    """
    report = build_report(
        detections,
        size_metric,
        extraction,
        repository=repository,
        dockerfile_path=dockerfile_path,
        commit_before=commit_before,
        commit_after=commit_after,
        tool_versions=tool_versions,
        timestamp=timestamp,
    )

    destination = Path(output_dir)
    raw_dir = destination / RAW_DATA_DIRNAME
    raw_dir.mkdir(parents=True, exist_ok=True)

    report_path = destination / REPORT_FILENAME
    summary_path = destination / SUMMARY_FILENAME

    _write(report_path, to_json(report))
    _write(summary_path, to_text(report))
    # The artifacts are written as they were retained: the value of each state
    # is the tool's own output text, embedded without re-serialisation so it
    # stays the evidence rather than a normalised copy of it.
    _write(raw_dir / TRIVY_RAW_FILENAME, _raw_document(report.raw_data["trivy"]))
    _write(raw_dir / HADOLINT_RAW_FILENAME, _raw_document(report.raw_data["hadolint"]))

    return ReportArtifacts(
        report_json=report_path, summary_text=summary_path, raw_data_dir=raw_dir
    )


def _raw_document(per_state: Mapping[str, str]) -> str:
    """One tool's retained output for both states, as a single JSON document.

    Each state's text is embedded as a parsed value rather than as a quoted
    string, so the artifact remains machine-readable end to end and a consumer
    can query it without a second decoding step. A state whose text is not
    valid JSON — which would mean the tool emitted something unexpected — is
    kept as a raw string instead of being discarded.
    """
    document = {}
    for state, text in per_state.items():
        try:
            document[state] = json.loads(text)
        except json.JSONDecodeError:
            document[state] = text
    return json.dumps(document, indent=2, ensure_ascii=False)


def _write(path: Path, content: str) -> None:
    """Write text as UTF-8 with LF endings, whatever the host platform."""
    path.write_text(content + "\n", encoding="utf-8", newline="\n")
