"""Unit tests for the Data Extractor (RF5, RF6, RNF2, RNF4, RNF5).

The external tools are replaced by a fake ``subprocess.run`` that serves
recorded Trivy and Hadolint JSON, so the suite runs without a daemon and
without pulling either tool image. The end-to-end test invokes the real
containers and is skipped when Docker is not reachable.
"""

import json
import subprocess

import pytest

from src import data_extractor
from src.data_extractor import (
    MAINTAINABILITY_SCREEN,
    DataExtractorError,
    count_logical_instructions,
    extract_metrics,
)

IMAGE_BEFORE = "sha256:imagebefore"
IMAGE_AFTER = "sha256:imageafter"

DOCKERFILE_A = "FROM ubuntu:latest\nRUN apt-get install curl\nCMD /bin/sh\n"
DOCKERFILE_B = "FROM ubuntu:22.04\nRUN apt-get install -y curl=7.81.0\nCMD [\"/bin/sh\"]\n"


# --- Fake tool invocation ---------------------------------------------------------


def _trivy_report(vulnerabilities):
    """A Trivy JSON report carrying the given (id, severity) pairs."""
    return json.dumps(
        {
            "Results": [
                {
                    "Target": "image",
                    "Vulnerabilities": [
                        {"VulnerabilityID": identifier, "Severity": severity}
                        for identifier, severity in vulnerabilities
                    ],
                }
            ]
        }
    ).encode("utf-8")


def _hadolint_report(codes):
    """A Hadolint JSON report carrying one finding per given rule code."""
    return json.dumps(
        [{"code": code, "level": "warning", "line": 1} for code in codes]
    ).encode("utf-8")


class FakeTools:
    """Serves recorded output per tool invocation, recording the commands."""

    def __init__(self, scans, lints, failures=None):
        self.scans = scans  # image reference -> stdout bytes
        self.lints = lints  # list of stdout bytes, in call order
        self.failures = failures or {}  # "trivy"/"hadolint" -> exception
        self.commands = []
        self._lint_calls = 0

    def __call__(self, command, input=None, stdout=None, stderr=None, timeout=None, check=False):
        self.commands.append(list(command))
        tool = "trivy" if data_extractor.TRIVY_IMAGE in command else "hadolint"
        if tool in self.failures:
            raise self.failures[tool]
        if tool == "trivy":
            payload = self.scans[command[-1]]
        else:
            payload = self.lints[min(self._lint_calls, len(self.lints) - 1)]
            self._lint_calls += 1
        return subprocess.CompletedProcess(command, 0, stdout=payload, stderr=b"")


@pytest.fixture
def fake_tools(monkeypatch):
    """Install fake tool output and hand the test a factory to configure it."""

    def install(scans=None, lints=None, failures=None):
        if scans is None:
            scans = {IMAGE_BEFORE: _trivy_report([]), IMAGE_AFTER: _trivy_report([])}
        if lints is None:
            lints = [_hadolint_report([]), _hadolint_report([])]
        tools = FakeTools(scans, lints, failures)
        monkeypatch.setattr(subprocess, "run", tools)
        return tools

    return install


# --- The 47-rule maintainability screen -------------------------------------------


def test_the_screen_holds_exactly_forty_seven_distinct_rules():
    assert len(MAINTAINABILITY_SCREEN) == 47
    assert len(set(MAINTAINABILITY_SCREEN)) == 47


def test_the_screen_excludes_rules_disabled_by_default_in_hadolint():
    # Appendix C: the label-schema rules DL3049-DL3058 and the optional
    # HEALTHCHECK rule DL3057 never fire unless configured.
    disabled = {f"DL30{number}" for number in range(49, 59)}
    assert disabled.isdisjoint(MAINTAINABILITY_SCREEN)


def test_only_screened_rules_are_counted(fake_tools):
    # DL3007 and DL3008 are in the screen; DL3002 and DL3059 are not.
    fake_tools(
        lints=[
            _hadolint_report(["DL3007", "DL3008", "DL3002", "DL3059"]),
            _hadolint_report([]),
        ]
    )
    result = extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)
    assert result.before.warnings == 2  # the two off-screen findings ignored
    assert result.delta_warnings == -2


def test_repeated_violations_of_one_rule_are_all_counted(fake_tools):
    # The metric is the global sum of violations, not the number of rules hit.
    fake_tools(lints=[_hadolint_report(["DL3008", "DL3008", "DL3008"]), _hadolint_report([])])
    result = extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)
    assert result.before.warnings == 3


def test_eliminating_one_rule_violation_yields_a_delta_of_minus_one(fake_tools):
    # RNF2 diagnostic sensitivity: the PoC-2 acceptance criterion for DL3007.
    fake_tools(lints=[_hadolint_report(["DL3007"]), _hadolint_report([])])
    result = extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)
    assert result.delta_warnings == -1


# --- ΔCVEs ------------------------------------------------------------------------


def test_distinct_identifiers_are_counted_once(fake_tools):
    # RF5: one vulnerability affecting several packages counts once.
    fake_tools(
        scans={
            IMAGE_BEFORE: _trivy_report(
                [("CVE-1", "HIGH"), ("CVE-1", "HIGH"), ("CVE-2", "LOW")]
            ),
            IMAGE_AFTER: _trivy_report([]),
        }
    )
    result = extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)
    assert result.before.cves == 2
    assert result.delta_cves == -2


def test_cves_are_reported_by_severity_tier(fake_tools):
    fake_tools(
        scans={
            IMAGE_BEFORE: _trivy_report(
                [("CVE-1", "CRITICAL"), ("CVE-2", "HIGH"), ("CVE-3", "HIGH")]
            ),
            IMAGE_AFTER: _trivy_report([("CVE-2", "HIGH")]),
        }
    )
    result = extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)
    assert result.before.cves_by_severity["CRITICAL"] == 1
    assert result.before.cves_by_severity["HIGH"] == 2
    assert result.delta_cves_by_severity["CRITICAL"] == -1
    assert result.delta_cves_by_severity["HIGH"] == -1


def test_an_unknown_severity_counts_in_the_total_but_in_no_tier(fake_tools):
    fake_tools(
        scans={
            IMAGE_BEFORE: _trivy_report([("CVE-1", "MODERATE"), ("CVE-2", "HIGH")]),
            IMAGE_AFTER: _trivy_report([]),
        }
    )
    result = extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)
    assert result.before.cves == 2
    assert sum(result.before.cves_by_severity.values()) == 1


def test_a_clean_image_yields_zero_and_not_an_error(fake_tools):
    # Trivy omits Vulnerabilities entirely when an image is clean.
    fake_tools(
        scans={
            IMAGE_BEFORE: json.dumps({"Results": [{"Target": "image"}]}).encode(),
            IMAGE_AFTER: json.dumps({"Results": None}).encode(),
        }
    )
    result = extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)
    assert result.before.cves == 0 and result.after.cves == 0
    assert result.delta_cves == 0


# --- ΔInstr -----------------------------------------------------------------------


def test_logical_instructions_exclude_comments():
    content = "# a comment\nFROM alpine:3.20\n# another\nCMD [\"sh\"]\n"
    assert count_logical_instructions(content) == 2


def test_a_multiline_instruction_counts_as_one():
    # RF6: backslash continuations resolve to a single logical unit.
    content = "FROM alpine:3.20\nRUN apk add --no-cache \\\n    curl \\\n    git\n"
    assert count_logical_instructions(content) == 2


def test_logical_instructions_tolerate_crlf_line_endings():
    content = "FROM alpine:3.20\r\nRUN echo a \\\r\n  && echo b\r\n"
    assert count_logical_instructions(content) == 2


def test_a_single_added_instruction_moves_the_delta_by_one(fake_tools):
    # RNF2 structural sensitivity.
    fake_tools()
    result = extract_metrics(
        "FROM alpine:3.20\nCMD [\"sh\"]\n",
        "FROM alpine:3.20\nENV MODE=prod\nCMD [\"sh\"]\n",
        IMAGE_BEFORE,
        IMAGE_AFTER,
    )
    assert result.delta_logical_instructions == 1


def test_the_component_parses_independently_of_the_detection_engine():
    # The two must not share code: a change to detection cannot be allowed to
    # move a maintainability metric.
    source = (data_extractor.__file__)
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    assert "detection_engine" not in text


# --- Component boundaries ----------------------------------------------------------


def test_the_component_never_builds_or_removes_images(fake_tools):
    tools = fake_tools()
    extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)
    for command in tools.commands:
        assert "build" not in command
        assert "rmi" not in command and "remove" not in command


def test_both_images_are_scanned_read_only(fake_tools):
    tools = fake_tools()
    extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)
    scanned = [command[-1] for command in tools.commands if data_extractor.TRIVY_IMAGE in command]
    assert sorted(scanned) == sorted([IMAGE_BEFORE, IMAGE_AFTER])


def test_scans_share_one_trivy_database_cache(fake_tools):
    # RNF5: without the shared volume every --rm scan re-downloads the database
    # and no database version can be recorded for the report.
    tools = fake_tools()
    extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)
    scan_commands = [c for c in tools.commands if data_extractor.TRIVY_IMAGE in c]
    assert len(scan_commands) == 2
    for command in scan_commands:
        assert any(data_extractor.TRIVY_CACHE_VOLUME in token for token in command)


def test_hadolint_reads_the_dockerfile_from_stdin(fake_tools):
    # No temporary Dockerfile is written to the working directory.
    tools = fake_tools()
    extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)
    lint_commands = [c for c in tools.commands if data_extractor.HADOLINT_IMAGE in c]
    assert len(lint_commands) == 2
    for command in lint_commands:
        assert command[-1] == "-"  # stdin, not a path


# --- Exception contract (RNF4) ------------------------------------------------------


def test_a_missing_docker_command_raises_data_extractor_error(fake_tools):
    fake_tools(failures={"trivy": FileNotFoundError("docker")})
    with pytest.raises(DataExtractorError, match="docker command is not available"):
        extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)


def test_a_tool_timeout_raises_data_extractor_error(fake_tools):
    fake_tools(failures={"trivy": subprocess.TimeoutExpired("docker", 600)})
    with pytest.raises(DataExtractorError, match="did not finish"):
        extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)


def test_empty_tool_output_raises_data_extractor_error(fake_tools):
    fake_tools(scans={IMAGE_BEFORE: b"", IMAGE_AFTER: _trivy_report([])})
    with pytest.raises(DataExtractorError, match="produced no output"):
        extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)


def test_malformed_tool_json_raises_data_extractor_error(fake_tools):
    fake_tools(scans={IMAGE_BEFORE: b"not json at all", IMAGE_AFTER: _trivy_report([])})
    with pytest.raises(DataExtractorError, match="did not return valid JSON"):
        extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)


def test_an_unexpected_trivy_shape_raises_data_extractor_error(fake_tools):
    fake_tools(scans={IMAGE_BEFORE: b"[1, 2, 3]", IMAGE_AFTER: _trivy_report([])})
    with pytest.raises(DataExtractorError, match="unexpected shape"):
        extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)


@pytest.mark.parametrize(
    "report",
    [
        {"Results": ["not an object"]},
        {"Results": [{"Vulnerabilities": ["not an object"]}]},
        {"Results": [{"Vulnerabilities": [42]}]},
    ],
    ids=["result-not-object", "vulnerability-not-object", "vulnerability-is-int"],
)
def test_a_malformed_trivy_traversal_raises_data_extractor_error(fake_tools, report):
    # A truncated report must not let an AttributeError escape from the middle
    # of the walk: RNF4 requires every external failure to be diagnosable.
    fake_tools(
        scans={IMAGE_BEFORE: json.dumps(report).encode(), IMAGE_AFTER: _trivy_report([])}
    )
    with pytest.raises(DataExtractorError, match="unexpected shape"):
        extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)


def test_a_vulnerability_without_an_identifier_is_skipped(fake_tools):
    fake_tools(
        scans={
            IMAGE_BEFORE: json.dumps(
                {"Results": [{"Vulnerabilities": [{"Severity": "HIGH"}, {"VulnerabilityID": "CVE-1", "Severity": "LOW"}]}]}
            ).encode(),
            IMAGE_AFTER: _trivy_report([]),
        }
    )
    result = extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)
    assert result.before.cves == 1


def test_a_hadolint_finding_that_is_not_an_object_is_skipped(fake_tools):
    fake_tools(lints=[json.dumps(["DL3007", None, {"code": "DL3008"}]).encode(), _hadolint_report([])])
    result = extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)
    assert result.before.warnings == 1  # only the well-formed DL3008 finding


def test_an_unexpected_hadolint_shape_raises_data_extractor_error(fake_tools):
    fake_tools(lints=[b"{\"not\": \"a list\"}", _hadolint_report([])])
    with pytest.raises(DataExtractorError, match="unexpected shape"):
        extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)


def test_malformed_dockerfile_content_raises_data_extractor_error():
    with pytest.raises(DataExtractorError, match="must be a string"):
        count_logical_instructions(None)


def test_parsing_fails_before_any_image_is_scanned(fake_tools):
    # A malformed Dockerfile is cheap to detect; two scans are not.
    tools = fake_tools()
    with pytest.raises(DataExtractorError):
        extract_metrics(DOCKERFILE_A, None, IMAGE_BEFORE, IMAGE_AFTER)
    assert tools.commands == []


# --- Deltas -------------------------------------------------------------------------


def test_all_three_deltas_are_after_minus_before(fake_tools):
    fake_tools(
        scans={
            IMAGE_BEFORE: _trivy_report([("CVE-1", "HIGH"), ("CVE-2", "LOW")]),
            IMAGE_AFTER: _trivy_report([("CVE-1", "HIGH")]),
        },
        lints=[_hadolint_report(["DL3007", "DL3008"]), _hadolint_report(["DL3008"])],
    )
    result = extract_metrics(
        "FROM ubuntu:latest\nRUN apt-get install curl\n",
        "FROM ubuntu:22.04\nRUN apt-get install -y curl\nENV MODE=prod\n",
        IMAGE_BEFORE,
        IMAGE_AFTER,
    )
    assert result.delta_cves == -1  # 2 -> 1
    assert result.delta_warnings == -1  # 2 -> 1
    assert result.delta_logical_instructions == 1  # 2 -> 3


def test_the_raw_tool_output_is_retained_for_both_states(fake_tools):
    # RNF5: the source analysis artifacts must survive the extraction, so a
    # counted metric can be traced back to the finding that produced it.
    trivy_before = _trivy_report([("CVE-1", "HIGH")])
    hadolint_before = _hadolint_report(["DL3007"])
    fake_tools(
        scans={IMAGE_BEFORE: trivy_before, IMAGE_AFTER: _trivy_report([])},
        lints=[hadolint_before, _hadolint_report([])],
    )
    result = extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)

    assert set(result.raw_trivy) == {"before", "after"}
    assert set(result.raw_hadolint) == {"before", "after"}
    assert result.raw_trivy["before"] == trivy_before.decode("utf-8")
    assert result.raw_hadolint["before"] == hadolint_before.decode("utf-8")


def test_the_retained_artifacts_are_verbatim_and_not_re_serialised(fake_tools):
    # Unusual spacing and key order must survive: re-serialising from the
    # parsed object would normalise both and stop it being the artifact.
    quirky = b'{"Results":[   {"Vulnerabilities":[{"Severity":"HIGH","VulnerabilityID":"CVE-1"}]}]}'
    fake_tools(scans={IMAGE_BEFORE: quirky, IMAGE_AFTER: _trivy_report([])})
    result = extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)
    assert result.raw_trivy["before"] == quirky.decode("utf-8")
    assert result.before.cves == 1  # and it still parsed correctly


def test_the_retained_artifacts_are_the_ones_that_produced_the_counts(fake_tools):
    fake_tools(
        scans={
            IMAGE_BEFORE: _trivy_report([("CVE-1", "HIGH"), ("CVE-2", "LOW")]),
            IMAGE_AFTER: _trivy_report([("CVE-1", "HIGH")]),
        }
    )
    result = extract_metrics(DOCKERFILE_A, DOCKERFILE_B, IMAGE_BEFORE, IMAGE_AFTER)
    # The retained text must account for exactly the counted identifiers.
    for state, expected in (("before", 2), ("after", 1)):
        identifiers = {
            v["VulnerabilityID"]
            for r in json.loads(result.raw_trivy[state])["Results"]
            for v in r["Vulnerabilities"]
        }
        assert len(identifiers) == expected


def test_zero_deltas_are_a_result_and_not_an_absence(fake_tools):
    # A refactoring that moves none of the three indicators reports zeroes.
    fake_tools(
        scans={
            IMAGE_BEFORE: _trivy_report([("CVE-1", "HIGH")]),
            IMAGE_AFTER: _trivy_report([("CVE-1", "HIGH")]),
        },
        lints=[_hadolint_report(["DL3008"]), _hadolint_report(["DL3008"])],
    )
    result = extract_metrics(DOCKERFILE_A, DOCKERFILE_A, IMAGE_BEFORE, IMAGE_AFTER)
    assert (result.delta_cves, result.delta_warnings, result.delta_logical_instructions) == (0, 0, 0)


# --- Tool provenance (RNF5) -----------------------------------------------------------


class FakeVersions:
    """Serves version output for the two provenance queries."""

    def __init__(self, hadolint, trivy, failures=None):
        self.hadolint = hadolint
        self.trivy = trivy
        self.failures = failures or {}
        self.commands = []

    def __call__(self, command, input=None, stdout=None, stderr=None, timeout=None, check=False):
        self.commands.append(list(command))
        tool = "trivy" if data_extractor.TRIVY_IMAGE in command else "hadolint"
        if tool in self.failures:
            raise self.failures[tool]
        payload = self.trivy if tool == "trivy" else self.hadolint
        return subprocess.CompletedProcess(command, 0, stdout=payload, stderr=b"")


@pytest.fixture
def fake_versions(monkeypatch):
    def install(hadolint=b"Haskell Dockerfile Linter 2.14.0\n", trivy=None, failures=None):
        if trivy is None:
            trivy = json.dumps(
                {
                    "Version": "0.72.0",
                    "VulnerabilityDB": {"UpdatedAt": "2026-08-10T01:00:06Z"},
                }
            ).encode()
        versions = FakeVersions(hadolint, trivy, failures)
        monkeypatch.setattr(subprocess, "run", versions)
        return versions

    return install


def test_provenance_reports_all_three_versions(fake_versions):
    fake_versions()
    provenance = data_extractor.tool_provenance()
    assert provenance.hadolint_version == "Haskell Dockerfile Linter 2.14.0"
    assert provenance.trivy_version == "0.72.0"
    assert provenance.trivy_db_version == "2026-08-10T01:00:06Z"


def test_provenance_queries_trivy_against_the_shared_database_cache(fake_versions):
    # The database version must be the one the scans used, not an empty cache.
    versions = fake_versions()
    data_extractor.tool_provenance()
    trivy_command = next(c for c in versions.commands if data_extractor.TRIVY_IMAGE in c)
    assert any(data_extractor.TRIVY_CACHE_VOLUME in token for token in trivy_command)


def test_provenance_reports_an_unpopulated_database_without_inventing_a_version(fake_versions):
    # Trivy omits the database block entirely until a scan has populated the
    # cache; that must read as unavailable rather than as a version.
    fake_versions(trivy=json.dumps({"Version": "0.72.0"}).encode())
    provenance = data_extractor.tool_provenance()
    assert provenance.trivy_version == "0.72.0"
    assert provenance.trivy_db_version == "not yet downloaded"


def test_provenance_surfaces_a_missing_docker_command(fake_versions):
    fake_versions(failures={"hadolint": FileNotFoundError("docker")})
    with pytest.raises(DataExtractorError, match="docker command is not available"):
        data_extractor.tool_provenance()


def test_provenance_surfaces_malformed_trivy_version_output(fake_versions):
    fake_versions(trivy=b"not json")
    with pytest.raises(DataExtractorError, match="did not return valid JSON"):
        data_extractor.tool_provenance()


def test_provenance_rejects_an_unexpected_trivy_version_shape(fake_versions):
    fake_versions(trivy=b"[\"0.72.0\"]")
    with pytest.raises(DataExtractorError, match="unexpected shape"):
        data_extractor.tool_provenance()


# --- Integration: requires a running Docker daemon ------------------------------------


def _daemon_available() -> bool:
    try:
        return subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
    except Exception:  # noqa: BLE001 — any failure means no usable daemon
        return False


@pytest.mark.skipif(not _daemon_available(), reason="Docker daemon not reachable")
def test_end_to_end_against_the_real_tools():
    """RF5/RF6 end to end: real Hadolint and Trivy against two real images."""
    from src.image_builder import build_image_pair

    # DL3000 (absolute WORKDIR) and DL3025 (JSON notation for CMD) are both in
    # the screen and both fixed by the after state. Neither depends on package
    # resolution, so the pair builds from the base image alone.
    before = "FROM alpine:3.20\nWORKDIR app\nCMD /bin/sh\n"
    after = "FROM alpine:3.20\nWORKDIR /app\nCMD [\"/bin/sh\"]\n"

    with build_image_pair(before, after) as pair:
        result = extract_metrics(before, after, pair.image_before, pair.image_after)

    assert result.before.warnings == 2
    assert result.after.warnings == 0
    assert result.delta_warnings == -2
    assert result.delta_logical_instructions == 0  # 3 -> 3
    assert result.before.cves >= 0 and result.after.cves >= 0
