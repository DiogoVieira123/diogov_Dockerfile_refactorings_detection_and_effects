"""Data Extractor — security and maintainability metrics (Chapter 5, Section 5.6).

Stage 3 measurement component, running in parallel with the Performance
Analyzer. It receives the two Dockerfile states and the references to the two
images Stage 3's preparation built, and returns three signed deltas (RF5, RF6):

* ΔCVEs — distinct vulnerability identifiers reported by Trivy against each
  built image, overall and by severity tier;
* ΔWarnings — Hadolint findings on each Dockerfile text, restricted to the
  47-rule maintainability screen;
* ΔInstr — logical instructions of each Dockerfile text, COMMENT excluded.

The component measures and nothing else. It does not build images and it does
not remove them: both belong to the preparation stage (``image_builder``), and
the images arrive here as identifiers consumed strictly read-only. It never
reads a value produced by the Performance Analyzer either — its three metrics
are computed without ΔSize, just as ΔSize is computed without them. That mutual
independence is what allows the two measurement components to run concurrently;
this module holds no state and shares no object with its sibling.

Internally the two external tools are invoked concurrently, since a Trivy image
scan and a Hadolint text analysis have nothing to say to each other and the
scan dominates the elapsed time.

Both tools run as containers, through the same commands the extended-catalogue
experiments use, so the values this component produces are directly comparable
with the recorded ones. Both are invoked in JSON mode and their heterogeneous
schemas are normalised here into one metric representation (RF5).

All external tool failures — a missing daemon, a container that fails, output
that is not the expected JSON — surface as :class:`DataExtractorError` (RNF4),
so the pipeline can distinguish an extraction failure from a defect of its own
or from a measurement failure in the sibling component.
"""

from __future__ import annotations

import concurrent.futures
import io
import json
import subprocess
from typing import Dict, List, NamedTuple, Optional, Sequence

from dockerfile_parse import DockerfileParser


class DataExtractorError(Exception):
    """A security or maintainability metric could not be extracted.

    RNF4: every external tool failure — Trivy or Hadolint unavailable, a
    container exiting in error, output that cannot be parsed as the documented
    JSON schema — is re-raised as this exception with the underlying cause
    attached, so the pipeline can tell an extraction failure from a build
    failure upstream (``ImageBuildError``), a size measurement failure in the
    sibling component (``PerformanceAnalyzerError``), or a bug in its own logic.
    """


# --- The 47-rule maintainability screen ------------------------------------------

# Appendix C. Derived by dimensional exclusion from the default rule sets of
# Hadolint and ShellCheck: rules targeting image size or layer cache were
# removed because ΔSize already captures that effect, and rules targeting
# security surfaces were removed because ΔCVEs already captures theirs. What
# remains isolates structural correctness, clean notation and maintainable
# authoring practices. Rules disabled by default in Hadolint — the label-schema
# rules DL3049–DL3058 and the optional HEALTHCHECK rule DL3057 — are absent,
# since they never fire unless explicitly configured.
#
# Held as a declarative list so it can be inspected and revised independently
# of the parsing logic.
MAINTAINABILITY_SCREEN: Sequence[str] = (
    # Reproducibility (16)
    "DL3005", "DL3006", "DL3007", "DL3008", "DL3013", "DL3016", "DL3017",
    "DL3018", "DL3028", "DL3031", "DL3033", "DL3035", "DL3037", "DL3039",
    "DL3041", "DL3062",
    # Structural correctness (15)
    "DL3000", "DL3003", "DL3011", "DL3012", "DL3021", "DL3022", "DL3023",
    "DL3024", "DL3043", "DL3044", "DL3045", "DL3061", "DL3063", "DL4003",
    "DL4004",
    # Usage and notation (12)
    "DL3001", "DL3010", "DL3014", "DL3025", "DL3027", "DL3029", "DL3030",
    "DL3034", "DL3038", "DL4001", "DL4005", "DL4006",
    # Metadata (1)
    "DL4000",
    # Shell correctness, ShellCheck (2)
    "SC2046", "SC2086",
    # Build logs (1)
    "DL3047",
)

_SCREEN = frozenset(MAINTAINABILITY_SCREEN)

# Severity tiers Trivy reports, ordered from most to least severe. Findings
# carrying any other severity are counted in the total but in no tier.
SEVERITY_TIERS: Sequence[str] = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")


# --- Metric structures ------------------------------------------------------------


class MetricSet(NamedTuple):
    """The three indicators measured for one Dockerfile state.

    One instance per state; the deltas are the signed difference between two
    of them, always ``after`` minus ``before``.
    """

    cves: int  # distinct vulnerability identifiers, all severities
    cves_by_severity: Dict[str, int]  # distinct identifiers per severity tier
    warnings: int  # Hadolint findings within the 47-rule screen
    instructions: int  # logical instructions, COMMENT excluded


class ExtractionResult(NamedTuple):
    """Both states, the three deltas, and the raw tool output (RF5, RF6, RNF5).

    The sign convention is the study's: ``after`` minus ``before``, so a
    negative delta is an improvement for all three indicators.

    ``raw_hadolint`` and ``raw_trivy`` carry the source analysis artifacts
    verbatim, keyed by state. RNF5 requires reproducibility to rest not only on
    recorded versions but on the capability to retain what the external tools
    actually emitted, so a counted metric can be traced back to the finding
    that produced it and a future re-run can be compared against the original
    evidence rather than against a number alone. The text is kept exactly as
    the tool wrote it — never re-serialised from the parsed object, which would
    silently normalise key order and whitespace and stop it being the artifact.
    """

    before: MetricSet
    after: MetricSet
    delta_cves: int
    delta_cves_by_severity: Dict[str, int]
    delta_warnings: int
    delta_logical_instructions: int
    raw_hadolint: Dict[str, str]  # {"before": <json text>, "after": <json text>}
    raw_trivy: Dict[str, str]  # {"before": <json text>, "after": <json text>}


class ToolProvenance(NamedTuple):
    """Versions RNF5 requires the report to record.

    The Trivy vulnerability database version is what allows a future re-run to
    tell a CVE delta caused by a Dockerfile change from one caused by a
    database update.
    """

    hadolint_version: str
    trivy_version: str
    trivy_db_version: str


# --- External tool invocation -----------------------------------------------------

# Deliberately untagged, so both resolve to :latest. This is the exact
# invocation the extended-catalogue experiments use, and parity with the
# validated protocol was chosen over pinning: a pinned tag here would measure
# with a different tool build than the one that produced the recorded values.
# The cost is that the tool version is a property of when the analysis ran
# rather than of the code, which is why `tool_provenance()` records it in every
# report (RNF5).
HADOLINT_IMAGE = "hadolint/hadolint"
TRIVY_IMAGE = "aquasec/trivy"

# Trivy inspects images held by the local daemon, so it needs the socket.
_DOCKER_SOCKET = "/var/run/docker.sock:/var/run/docker.sock"

# Trivy keeps its vulnerability database in a cache directory. A container
# started with --rm loses it, so without a persistent volume every scan
# re-downloads the database and, more importantly for RNF5, `trivy version`
# reports no database metadata at all. The named volume gives the two scans
# and the version query one shared database, which is what makes the recorded
# database version the one the measurements actually used.
TRIVY_CACHE_VOLUME = "dockerfile-refactoring-trivy-cache"
_TRIVY_CACHE = f"{TRIVY_CACHE_VOLUME}:/root/.cache/trivy"

_TOOL_TIMEOUT_SECONDS = 600


def _run(command: Sequence[str], label: str, stdin: Optional[bytes] = None) -> bytes:
    """Run one containerised tool and return its stdout.

    Args:
        command: the full argument vector, starting with ``docker``.
        label: what is being run, used only so the diagnostic identifies it.
        stdin: bytes to feed the container, for tools reading from stdin.

    Raises:
        DataExtractorError: the Docker CLI is absent, the container exits in
            error, or it does not finish within the timeout (RNF4).
    """
    try:
        completed = subprocess.run(
            list(command),
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_TOOL_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DataExtractorError(
            f"Could not run {label}: the docker command is not available."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DataExtractorError(
            f"{label} did not finish within {_TOOL_TIMEOUT_SECONDS} seconds."
        ) from exc

    # Hadolint exits non-zero when it reports findings, which is the normal
    # case here, so the exit code alone cannot signal failure. An empty stdout
    # is what distinguishes a tool that ran from one that did not.
    if not completed.stdout.strip():
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise DataExtractorError(
            f"{label} produced no output (exit code {completed.returncode})"
            + (f": {detail.splitlines()[-1][:200]}" if detail else ".")
        )
    return completed.stdout


def _parse_json(payload: bytes, label: str):
    """Decode a tool's JSON output.

    Raises:
        DataExtractorError: the output is not the documented JSON (RNF4).
    """
    try:
        return json.loads(payload.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise DataExtractorError(
            f"{label} did not return valid JSON: {exc}"
        ) from exc


# --- ΔCVEs — Trivy ----------------------------------------------------------------


def _scan_image(image_reference: str, label: str) -> bytes:
    """Run a Trivy vulnerability scan against one built image, in JSON mode."""
    return _run(
        [
            "docker", "run", "--rm",
            "-v", _DOCKER_SOCKET,
            "-v", _TRIVY_CACHE,
            TRIVY_IMAGE, "image", "--quiet", "--format", "json",
            image_reference,
        ],
        f"Trivy scan of the '{label}' image",
    )


def _count_distinct_cves(report) -> Dict[str, int]:
    """Distinct vulnerability identifiers in a Trivy report, overall and by tier.

    RF5 counts distinct identifiers rather than occurrences, so a single
    vulnerability affecting several packages is counted once. Deduplication is
    therefore global across the report's results, not per result: the same CVE
    reported for two packages contributes one identifier to the total.

    A vulnerability whose severity is absent or outside the known tiers still
    counts towards the total, so the tiers never exceed it but may sum to less.

    The traversal is guarded: a truncated or otherwise malformed report whose
    nested members are not the documented objects raises DataExtractorError
    like any other tool failure, rather than letting an AttributeError from the
    middle of the walk escape as an unhandled error (RNF4).
    """
    if not isinstance(report, dict):
        raise DataExtractorError(
            f"Trivy report has an unexpected shape: expected an object, got "
            f"{type(report).__name__}."
        )

    severity_of: Dict[str, str] = {}
    try:
        for result in report.get("Results") or []:
            for vulnerability in result.get("Vulnerabilities") or []:
                identifier = vulnerability.get("VulnerabilityID")
                if not identifier:
                    continue
                severity = str(vulnerability.get("Severity", "")).upper()
                # The first severity seen for an identifier is kept, so the
                # same CVE listed twice cannot inflate a tier.
                severity_of.setdefault(identifier, severity)
    except (AttributeError, TypeError) as exc:
        raise DataExtractorError(
            f"Trivy report has an unexpected shape: its results or "
            f"vulnerabilities are not the documented objects ({exc})."
        ) from exc

    counts = {tier: 0 for tier in SEVERITY_TIERS}
    for severity in severity_of.values():
        if severity in counts:
            counts[severity] += 1
    counts["TOTAL"] = len(severity_of)
    return counts


# --- ΔWarnings — Hadolint ---------------------------------------------------------


def _lint_dockerfile(dockerfile_content: str, label: str) -> bytes:
    """Run Hadolint against one Dockerfile text, in JSON mode.

    The content is fed on stdin rather than written to a file, so no temporary
    Dockerfile is left in the working directory and the text analysed is
    exactly the one the VCS Connector delivered. CRLF line endings are
    normalised first: blob content reflects whatever was committed.
    """
    payload = dockerfile_content.replace("\r\n", "\n").encode("utf-8")
    return _run(
        [
            "docker", "run", "--rm", "-i",
            HADOLINT_IMAGE, "hadolint", "--format", "json", "-",
        ],
        f"Hadolint analysis of the '{label}' Dockerfile",
        stdin=payload,
    )


def _count_screened_warnings(findings) -> int:
    """Hadolint findings whose rule belongs to the 47-rule screen.

    Every finding of a screened rule is counted, including several of the same
    rule on different lines: the metric is the global sum of maintainability
    violations, not the number of distinct rules violated.
    """
    if not isinstance(findings, list):
        raise DataExtractorError(
            f"Hadolint report has an unexpected shape: expected a list, got "
            f"{type(findings).__name__}."
        )
    return sum(1 for finding in findings if _rule_code(finding) in _SCREEN)


def _rule_code(finding) -> str:
    """Rule identifier of one Hadolint finding, or "" when absent."""
    if not isinstance(finding, dict):
        return ""
    return str(finding.get("code", ""))


# --- ΔInstr — dockerfile-parse ------------------------------------------------------


def count_logical_instructions(dockerfile_content: str) -> int:
    """Logical instructions of a Dockerfile text, COMMENT entries excluded (RF6).

    RF6 requires the count to come from the Dockerfile text and not from the
    built image, so that an instruction spanning several physical lines through
    backslash continuations resolves to a single logical unit.

    This component parses on its own account and shares no code with the
    Detection Engine. The two have different obligations — the engine needs
    each instruction's keyword and argument string to decide a refactoring,
    this component needs only how many there are — and coupling them would make
    a change to detection able to move a maintainability metric.

    Raises:
        DataExtractorError: the content is not text, or cannot be parsed (RNF4).
    """
    if not isinstance(dockerfile_content, str):
        raise DataExtractorError(
            f"Dockerfile content must be a string, got "
            f"{type(dockerfile_content).__name__}."
        )
    try:
        parser = DockerfileParser(fileobj=io.BytesIO())
        parser.content = dockerfile_content.replace("\r\n", "\n")
        structure = parser.structure
    except Exception as exc:  # noqa: BLE001 — any parser failure is malformed content
        raise DataExtractorError(
            f"Dockerfile content could not be parsed into logical "
            f"instructions: {exc}"
        ) from exc

    return sum(1 for entry in structure if entry["instruction"] != "COMMENT")


# --- Extraction --------------------------------------------------------------------


def extract_metrics(
    dockerfile_a: str,
    dockerfile_b: str,
    image_before: str,
    image_after: str,
) -> ExtractionResult:
    """Extract the three indicators for both states and the deltas (RF5, RF6).

    The component's entry point. Both images must already exist; building and
    removing them is the preparation's responsibility, and this function
    only reads them.

    The four external invocations — two Trivy scans and two Hadolint analyses —
    are dispatched concurrently, since none depends on another's result. The
    instruction count is computed in-process and needs no container.

    Args:
        dockerfile_a: Dockerfile content at the earlier commit.
        dockerfile_b: Dockerfile content at the later commit.
        image_before: ID or tag of the image built from the earlier state.
        image_after: ID or tag of the image built from the later state.

    Returns:
        The metrics of both states and the three signed deltas between them.

    Raises:
        DataExtractorError: any external tool fails, returns output that is not
            the documented JSON, or the Dockerfile content cannot be parsed
            (RNF4).
    """
    # Parsed first: a malformed Dockerfile is cheap to detect and there is no
    # reason to spend two image scans before failing on it.
    instructions_before = count_logical_instructions(dockerfile_a)
    instructions_after = count_logical_instructions(dockerfile_b)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            "scan_before": pool.submit(_scan_image, image_before, "before"),
            "scan_after": pool.submit(_scan_image, image_after, "after"),
            "lint_before": pool.submit(_lint_dockerfile, dockerfile_a, "before"),
            "lint_after": pool.submit(_lint_dockerfile, dockerfile_b, "after"),
        }
        # Every future is resolved before the first failure is raised, so no
        # container is left running behind an early return.
        outputs, failure = {}, None
        for name, future in futures.items():
            try:
                outputs[name] = future.result()
            except DataExtractorError as exc:
                failure = failure or exc
        if failure is not None:
            raise failure

    cves_before = _count_distinct_cves(_parse_json(outputs["scan_before"], "Trivy"))
    cves_after = _count_distinct_cves(_parse_json(outputs["scan_after"], "Trivy"))
    warnings_before = _count_screened_warnings(
        _parse_json(outputs["lint_before"], "Hadolint")
    )
    warnings_after = _count_screened_warnings(
        _parse_json(outputs["lint_after"], "Hadolint")
    )

    before = MetricSet(
        cves=cves_before["TOTAL"],
        cves_by_severity={tier: cves_before[tier] for tier in SEVERITY_TIERS},
        warnings=warnings_before,
        instructions=instructions_before,
    )
    after = MetricSet(
        cves=cves_after["TOTAL"],
        cves_by_severity={tier: cves_after[tier] for tier in SEVERITY_TIERS},
        warnings=warnings_after,
        instructions=instructions_after,
    )

    return ExtractionResult(
        before=before,
        after=after,
        delta_cves=after.cves - before.cves,
        delta_cves_by_severity={
            tier: after.cves_by_severity[tier] - before.cves_by_severity[tier]
            for tier in SEVERITY_TIERS
        },
        delta_warnings=after.warnings - before.warnings,
        delta_logical_instructions=after.instructions - before.instructions,
        # Retained verbatim: decoded from the bytes the tool wrote, never
        # re-serialised from the parsed object (RNF5).
        raw_hadolint={
            "before": outputs["lint_before"].decode("utf-8", errors="replace"),
            "after": outputs["lint_after"].decode("utf-8", errors="replace"),
        },
        raw_trivy={
            "before": outputs["scan_before"].decode("utf-8", errors="replace"),
            "after": outputs["scan_after"].decode("utf-8", errors="replace"),
        },
    )


def tool_provenance() -> ToolProvenance:
    """Versions of the external tools and of the Trivy vulnerability database.

    Exposed for the Report Generator, which records them in every report
    (RNF5). The database version is what lets a future re-run tell a CVE delta
    caused by a Dockerfile change from one caused by a database update.

    Raises:
        DataExtractorError: a tool cannot be reached or does not report a
            version (RNF4).
    """
    hadolint = _run(
        ["docker", "run", "--rm", HADOLINT_IMAGE, "hadolint", "--version"],
        "Hadolint version query",
    ).decode("utf-8", errors="replace").strip()

    trivy_report = _parse_json(
        _run(
            ["docker", "run", "--rm", "-v", _TRIVY_CACHE,
             TRIVY_IMAGE, "version", "--format", "json"],
            "Trivy version query",
        ),
        "Trivy version query",
    )
    if not isinstance(trivy_report, dict):
        raise DataExtractorError(
            "Trivy version query returned an unexpected shape."
        )
    # The database block is absent until a scan has populated the cache, so a
    # provenance query made before any extraction reports it as unavailable
    # rather than inventing a version.
    database = trivy_report.get("VulnerabilityDB") or {}
    return ToolProvenance(
        hadolint_version=hadolint,
        trivy_version=str(trivy_report.get("Version", "unknown")),
        trivy_db_version=str(database.get("UpdatedAt", "not yet downloaded")),
    )
