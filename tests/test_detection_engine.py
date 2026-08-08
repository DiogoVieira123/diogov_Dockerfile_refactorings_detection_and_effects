"""Detection Engine tests — one minimal mock Dockerfile pair per rule.

Each rule has a Before/After pair (per the project testing requirement) plus
negative cases asserting that non-matching changes yield an EMPTY result:
a false positive is a rule failure, not a near-miss.
"""

import pytest

from src.detection_engine import (
    DockerfileParseError,
    detect_refactorings,
    parse_instructions,
)


# --- RNF4: malformed content raises a specific exception -----------------------


def test_parse_rejects_non_text_content():
    with pytest.raises(DockerfileParseError):
        parse_instructions(b"FROM alpine:3.20\n")


def test_parse_rejects_none():
    with pytest.raises(DockerfileParseError):
        parse_instructions(None)


# --- R01 — Inline RUN Instructions ---------------------------------------------

# RF2 acceptance criterion: the 4-to-1 RUN consolidation of Experiment 5.
R01_BEFORE = """FROM ubuntu:22.04
RUN apt-get update
RUN apt-get install -y curl
RUN apt-get install -y git
RUN apt-get install -y python3
"""
R01_AFTER = """FROM ubuntu:22.04
RUN apt-get update && \\
    apt-get install -y curl && \\
    apt-get install -y git && \\
    apt-get install -y python3
"""


def test_r01_detects_four_to_one_consolidation():
    detections = detect_refactorings(R01_BEFORE, R01_AFTER)
    assert [d.refactoring_id for d in detections] == ["R01"]
    detection = detections[0]
    assert detection.refactoring_name == "Inline RUN Instructions"
    # the four merged RUNs and the single surviving one
    assert len(detection.instructions_before) == 4
    assert len(detection.instructions_after) == 1
    assert detection.instructions_before[0] == ("RUN", "apt-get update")


def test_r01_detects_with_crlf_line_endings():
    detections = detect_refactorings(
        R01_BEFORE.replace("\n", "\r\n"), R01_AFTER.replace("\n", "\r\n")
    )
    assert [d.refactoring_id for d in detections] == ["R01"]


def test_r01_detected_despite_noise_in_other_instructions():
    # Granular evaluation: the consolidation is R01 even when the commit also
    # edits a WORKDIR and a CMD.
    detections = detect_refactorings(
        "FROM alpine:3.20\nWORKDIR /app\nRUN echo a\nRUN echo b\nCMD [\"sh\"]\n",
        "FROM alpine:3.20\nWORKDIR /src\nRUN echo a && echo b\nCMD [\"bash\"]\n",
    )
    assert [d.refactoring_id for d in detections] == ["R01"]


def test_r01_partial_consolidation_reports_only_the_merged_runs():
    # 'RUN echo c' survives verbatim; only a and b were merged.
    detections = detect_refactorings(
        "FROM alpine:3.20\nRUN echo a\nRUN echo b\nRUN echo c\n",
        "FROM alpine:3.20\nRUN echo a && echo b\nRUN echo c\n",
    )
    assert [d.refactoring_id for d in detections] == ["R01"]
    detection = detections[0]
    assert detection.instructions_before == (("RUN", "echo a"), ("RUN", "echo b"))
    assert detection.instructions_after == (("RUN", "echo a && echo b"),)


def test_r01_detected_when_inlining_is_mixed_with_a_deletion():
    # Real commits combine inlining with cleanup: 'echo a' and 'echo b' were
    # merged while 'echo c' was dropped in the same change. The merge is
    # evidence enough, so R01 is reported and the dropped command is ignored.
    detections = detect_refactorings(
        "FROM alpine:3.20\nRUN echo a\nRUN echo b\nRUN echo c\n",
        "FROM alpine:3.20\nRUN echo a && echo b\n",
    )
    assert [d.refactoring_id for d in detections] == ["R01"]
    detection = detections[0]
    # only the two RUNs that were actually merged are reported
    assert detection.instructions_before == (("RUN", "echo a"), ("RUN", "echo b"))
    assert detection.instructions_after == (("RUN", "echo a && echo b"),)


def test_r01_not_triggered_by_plain_deletion():
    # No RUN joins commands from two previous ones: nothing was inlined, a
    # instruction was simply removed.
    detections = detect_refactorings(
        "FROM alpine:3.20\nRUN echo a\nRUN echo b\nRUN echo c\n",
        "FROM alpine:3.20\nRUN echo a\n",
    )
    assert detections == []


def test_r01_not_triggered_when_a_run_is_merely_dropped():
    detections = detect_refactorings(
        "FROM alpine:3.20\nRUN echo a\nRUN echo b\n",
        "FROM alpine:3.20\nRUN echo b\n",
    )
    assert detections == []


def test_r01_not_triggered_by_splitting_a_run():
    # Reverse path: one RUN split into several reintroduces the DL3059 smell.
    assert detect_refactorings(R01_AFTER, R01_BEFORE) == []


def test_r01_not_triggered_when_run_count_is_unchanged():
    detections = detect_refactorings(
        "FROM alpine:3.20\nRUN echo a\n", "FROM alpine:3.20\nRUN echo a && echo b\n"
    )
    assert detections == []

# --- Parsing ------------------------------------------------------------------

MULTILINE_RUN = (
    "FROM alpine:3.19\n"
    "RUN apk add --no-cache curl \\\n"
    "    && curl --version \\\n"
    "    && rm -rf /var/cache/apk/*\n"
)


def test_multiline_run_is_one_logical_instruction():
    instructions = parse_instructions(MULTILINE_RUN)
    assert [i.instruction for i in instructions] == ["FROM", "RUN"]


def test_crlf_input_parses_like_lf_input():
    crlf = MULTILINE_RUN.replace("\n", "\r\n")
    assert parse_instructions(crlf) == parse_instructions(MULTILINE_RUN)


# --- R02 — Update Base Image TAG (mock pair mirrors PoC-2) ---------------------

R02_BEFORE = "FROM ubuntu:latest\nRUN apt-get update\nCMD [\"bash\"]\n"
R02_AFTER = "FROM ubuntu:22.04\nRUN apt-get update\nCMD [\"bash\"]\n"


def test_r02_detects_tag_update():
    detections = detect_refactorings(R02_BEFORE, R02_AFTER)
    assert [d.refactoring_id for d in detections] == ["R02"]
    detection = detections[0]
    assert detection.refactoring_name == "Update Base Image TAG"
    assert detection.instructions_before[0].value == "ubuntu:latest"
    assert detection.instructions_after[0].value == "ubuntu:22.04"


def test_r02_detects_pinning_an_omitted_tag():
    # No explicit tag means "latest", so pinning it is still a tag update.
    detections = detect_refactorings(
        "FROM ubuntu\nRUN apt-get update\n", "FROM ubuntu:22.04\nRUN apt-get update\n"
    )
    assert [d.refactoring_id for d in detections] == ["R02"]


def test_r02_detects_pinned_to_pinned_version_bump():
    # A pinned->pinned bump is a legitimate directional tag update.
    detections = detect_refactorings(
        "FROM ubuntu:20.04\nCMD [\"sh\"]\n", "FROM ubuntu:22.04\nCMD [\"sh\"]\n"
    )
    assert [d.refactoring_id for d in detections] == ["R02"]


def test_r02_detects_with_crlf_line_endings():
    detections = detect_refactorings(
        R02_BEFORE.replace("\n", "\r\n"), R02_AFTER.replace("\n", "\r\n")
    )
    assert [d.refactoring_id for d in detections] == ["R02"]


def test_r02_preserves_platform_flag_and_alias():
    detections = detect_refactorings(
        "FROM --platform=$BUILDPLATFORM node:18-alpine AS base\nCMD [\"node\"]\n",
        "FROM --platform=$BUILDPLATFORM node:20-alpine AS base\nCMD [\"node\"]\n",
    )
    assert [d.refactoring_id for d in detections] == ["R02"]


def test_r02_detected_despite_noise_in_other_instructions():
    # Granular per-instruction evaluation: the FROM tag change is R02 even
    # when the commit also touches instructions outside the catalogue.
    detections = detect_refactorings(
        "FROM ubuntu:latest\nWORKDIR /app\nENV MODE=dev\n",
        "FROM ubuntu:22.04\nWORKDIR /src\nENV MODE=prod\n",
    )
    assert [d.refactoring_id for d in detections] == ["R02"]
    detection = detections[0]
    assert detection.instructions_before == (("FROM", "ubuntu:latest"),)
    assert detection.instructions_after == (("FROM", "ubuntu:22.04"),)


def test_r02_detected_when_run_also_changes():
    # Replaces the abandoned whole-file "purity" test: a RUN edited in the
    # same commit is common noise, and the FROM tag update is still R02.
    detections = detect_refactorings(
        "FROM ubuntu:latest\nRUN apt-get update\n",
        "FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y curl\n",
    )
    assert [d.refactoring_id for d in detections] == ["R02"]
    assert detections[0].instructions_after == (("FROM", "ubuntu:22.04"),)


def test_r02_multistage_reports_only_the_tag_only_from():
    # Each FROM is judged in isolation: the first stage substitutes the
    # image entity (an R10, reported by its own rule); only the second is
    # a tag update, and the R02 detection involves that FROM alone.
    detections = detect_refactorings(
        "FROM ubuntu:22.04 AS build\nRUN make\nFROM node:18 AS run\nCMD [\"node\"]\n",
        "FROM alpine:3.19 AS build\nRUN make\nFROM node:20 AS run\nCMD [\"node\"]\n",
    )
    assert [d.refactoring_id for d in detections] == ["R02", "R10"]
    r02 = detections[0]
    assert r02.instructions_before == (("FROM", "node:18 AS run"),)
    assert r02.instructions_after == (("FROM", "node:20 AS run"),)
    r10 = detections[1]
    assert r10.instructions_before == (("FROM", "ubuntu:22.04 AS build"),)
    assert r10.instructions_after == (("FROM", "alpine:3.19 AS build"),)


# --- R08 — Replace ADD with COPY (mock pair mirrors PoC-4) ----------------------

R08_BEFORE = "FROM alpine:3.19\nADD app.txt /app.txt\n"
R08_AFTER = "FROM alpine:3.19\nCOPY app.txt /app.txt\n"


def test_r08_detects_add_replaced_with_copy():
    detections = detect_refactorings(R08_BEFORE, R08_AFTER)
    assert [d.refactoring_id for d in detections] == ["R08"]
    detection = detections[0]
    assert detection.refactoring_name == "Replace ADD with COPY"
    assert detection.instructions_before == (("ADD", "app.txt /app.txt"),)
    assert detection.instructions_after == (("COPY", "app.txt /app.txt"),)


def test_r08_detects_multiple_replacements():
    detections = detect_refactorings(
        "FROM alpine:3.19\nADD a.txt /a.txt\nADD b.txt /b.txt\n",
        "FROM alpine:3.19\nCOPY a.txt /a.txt\nCOPY b.txt /b.txt\n",
    )
    assert [d.refactoring_id for d in detections] == ["R08"]
    assert len(detections[0].instructions_before) == 2


def test_r08_detects_with_crlf_line_endings():
    detections = detect_refactorings(
        R08_BEFORE.replace("\n", "\r\n"), R08_AFTER.replace("\n", "\r\n")
    )
    assert [d.refactoring_id for d in detections] == ["R08"]


def test_r08_detected_despite_noise_in_other_instructions():
    # Granular evaluation: the swap is R08 even when the commit also edits
    # a WORKDIR and a RUN.
    detections = detect_refactorings(
        "FROM alpine:3.19\nWORKDIR /app\nADD app.txt /app.txt\nRUN ls /\n",
        "FROM alpine:3.19\nWORKDIR /src\nCOPY app.txt /app.txt\nRUN ls -la /\n",
    )
    assert [d.refactoring_id for d in detections] == ["R08"]


def test_r02_and_r08_reported_together():
    # The example agreed with the author: FROM tag update + WORKDIR noise +
    # ADD->COPY swap must yield [R02, R08], in rule registration order.
    # The source is a regular file — an archive would be auto-extracted by
    # ADD but not by COPY, which would disqualify the swap as R08.
    detections = detect_refactorings(
        "FROM ubuntu:latest\nWORKDIR /app\nADD projeto.conf /src/\n",
        "FROM ubuntu:22.04\nWORKDIR /src\nCOPY projeto.conf /src/\n",
    )
    assert [d.refactoring_id for d in detections] == ["R02", "R08"]


def test_r08_not_triggered_by_reverse_swap():
    # COPY -> ADD reintroduces the DL3020 smell; it is not a refactoring.
    assert detect_refactorings(R08_AFTER, R08_BEFORE) == []


def test_r08_not_triggered_when_arguments_also_change():
    # Keyword swap with different destination: arguments not preserved.
    detections = detect_refactorings(
        "FROM alpine:3.19\nADD app.txt /app.txt\n",
        "FROM alpine:3.19\nCOPY app.txt /opt/app.txt\n",
    )
    assert detections == []


def test_r08_not_triggered_by_add_deletion():
    # The ADD vanished without a corresponding COPY: deletion, not R08.
    detections = detect_refactorings(
        "FROM alpine:3.19\nADD app.txt /app.txt\nCMD [\"sh\"]\n",
        "FROM alpine:3.19\nCMD [\"sh\"]\n",
    )
    assert detections == []


def test_r08_not_triggered_for_auto_extracted_archive():
    # ADD auto-extracts local tar archives into the destination; COPY does
    # not, so the swap changes the build result — not behaviour-preserving.
    detections = detect_refactorings(
        "FROM alpine:3.19\nADD app.tar.gz /opt/\n",
        "FROM alpine:3.19\nCOPY app.tar.gz /opt/\n",
    )
    assert detections == []


def test_r08_not_triggered_for_url_source():
    # ADD downloads remote URLs; COPY cannot, so the swap breaks the build.
    detections = detect_refactorings(
        "FROM alpine:3.19\nADD https://example.com/app.bin /usr/local/bin/app\n",
        "FROM alpine:3.19\nCOPY https://example.com/app.bin /usr/local/bin/app\n",
    )
    assert detections == []


def test_r08_not_triggered_by_preexisting_copy():
    # The COPY with identical arguments existed before; the ADD was simply
    # deleted, so there is no keyword swap to report.
    detections = detect_refactorings(
        "FROM alpine:3.19\nADD app.txt /app.txt\nCOPY app.txt /app.txt\n",
        "FROM alpine:3.19\nCOPY app.txt /app.txt\n",
    )
    assert detections == []


# --- R03 — Add ENV Variable -----------------------------------------------------

R03_BEFORE = "FROM alpine:3.19\nRUN echo hi\n"
R03_AFTER = "FROM alpine:3.19\nENV APP_VERSION=1.0\nRUN echo hi\n"


def test_r03_detects_added_env():
    detections = detect_refactorings(R03_BEFORE, R03_AFTER)
    assert [d.refactoring_id for d in detections] == ["R03"]
    detection = detections[0]
    assert detection.refactoring_name == "Add ENV Variable"
    assert detection.instructions_before == ()
    assert detection.instructions_after == (("ENV", "APP_VERSION=1.0"),)


def test_r03_detects_with_crlf_line_endings():
    detections = detect_refactorings(
        R03_BEFORE.replace("\n", "\r\n"), R03_AFTER.replace("\n", "\r\n")
    )
    assert [d.refactoring_id for d in detections] == ["R03"]


def test_r03_detected_despite_noise_in_other_instructions():
    # Granular evaluation: the new ENV is R03 even when the commit also
    # edits a WORKDIR and a RUN.
    detections = detect_refactorings(
        "FROM alpine:3.19\nWORKDIR /app\nRUN echo hi\n",
        "FROM alpine:3.19\nWORKDIR /src\nENV APP_VERSION=1.0\nRUN echo hello\n",
    )
    assert [d.refactoring_id for d in detections] == ["R03"]


def test_r03_detects_new_name_added_to_multi_variable_env():
    # 'ENV A=1' became 'ENV A=1 B=2': the instruction now declares the new
    # name B, so an ENV variable was added.
    detections = detect_refactorings(
        "FROM alpine:3.19\nENV A=1\n", "FROM alpine:3.19\nENV A=1 B=2\n"
    )
    assert [d.refactoring_id for d in detections] == ["R03"]


def test_r03_detects_legacy_space_separated_form():
    # Legacy syntax 'ENV MODE dev' declares the variable MODE.
    detections = detect_refactorings(
        "FROM alpine:3.19\nCMD [\"sh\"]\n",
        "FROM alpine:3.19\nENV MODE dev\nCMD [\"sh\"]\n",
    )
    assert [d.refactoring_id for d in detections] == ["R03"]


def test_r03_not_triggered_by_env_removal():
    # Reverse path: removing an ENV is not a catalogued refactoring.
    assert detect_refactorings(R03_AFTER, R03_BEFORE) == []


def test_r03_not_triggered_by_env_value_update():
    # Same variable name, new value: a modification, not an addition.
    detections = detect_refactorings(
        "FROM alpine:3.19\nENV MODE=dev\n", "FROM alpine:3.19\nENV MODE=prod\n"
    )
    assert detections == []


def test_r03_and_r02_reported_together():
    # Non-exclusion: a commit that pins the tag AND adds an ENV reports
    # both, in rule-registry order (R02 registered before R03).
    detections = detect_refactorings(
        "FROM ubuntu:latest\nCMD [\"sh\"]\n",
        "FROM ubuntu:22.04\nENV MODE=prod\nCMD [\"sh\"]\n",
    )
    assert [d.refactoring_id for d in detections] == ["R02", "R03"]


# --- R04 — Add ARG Instruction ---------------------------------------------------

R04_BEFORE = "FROM alpine:3.19\nCMD [\"sh\"]\n"
R04_AFTER = "ARG APP_VERSION=1.0\nFROM alpine:3.19\nCMD [\"sh\"]\n"


def test_r04_detects_added_arg():
    detections = detect_refactorings(R04_BEFORE, R04_AFTER)
    assert [d.refactoring_id for d in detections] == ["R04"]
    detection = detections[0]
    assert detection.refactoring_name == "Add ARG Instruction"
    assert detection.instructions_before == ()
    assert detection.instructions_after == (("ARG", "APP_VERSION=1.0"),)


def test_r04_detects_arg_without_default():
    # 'ARG NAME' (no default) declares the identifier just the same.
    detections = detect_refactorings(
        "FROM alpine:3.19\nCMD [\"sh\"]\n",
        "FROM alpine:3.19\nARG BUILD_ID\nCMD [\"sh\"]\n",
    )
    assert [d.refactoring_id for d in detections] == ["R04"]


def test_r04_detects_with_crlf_line_endings():
    detections = detect_refactorings(
        R04_BEFORE.replace("\n", "\r\n"), R04_AFTER.replace("\n", "\r\n")
    )
    assert [d.refactoring_id for d in detections] == ["R04"]


def test_r04_detected_despite_noise_in_other_instructions():
    # Granular evaluation: the new ARG is R04 even when the commit also
    # edits a WORKDIR and a CMD.
    detections = detect_refactorings(
        "FROM alpine:3.19\nWORKDIR /app\nCMD [\"sh\"]\n",
        "ARG APP_VERSION=1.0\nFROM alpine:3.19\nWORKDIR /src\nCMD [\"bash\"]\n",
    )
    assert [d.refactoring_id for d in detections] == ["R04"]


def test_r04_not_triggered_by_arg_removal():
    # Reverse path: removing an ARG is not a catalogued refactoring.
    assert detect_refactorings(R04_AFTER, R04_BEFORE) == []


def test_r04_not_triggered_by_default_value_update():
    # Same identifier, new default: a modification, not an addition.
    detections = detect_refactorings(
        "ARG VERSION=1.0\nFROM alpine:3.19\n", "ARG VERSION=2.0\nFROM alpine:3.19\n"
    )
    assert detections == []


def test_r03_and_r04_reported_together():
    # Non-exclusion: one commit adding an ENV and an ARG reports both, in
    # rule-registry order (R03 registered before R04).
    detections = detect_refactorings(
        "FROM alpine:3.19\nCMD [\"sh\"]\n",
        "ARG BUILD_ID=0\nFROM alpine:3.19\nENV MODE=prod\nCMD [\"sh\"]\n",
    )
    assert [d.refactoring_id for d in detections] == ["R03", "R04"]


# --- R10 — Update Base Image (mock pair mirrors PoC-3) ---------------------------

R10_BEFORE = "FROM ubuntu:22.04\nCMD [\"sh\"]\n"
R10_AFTER = "FROM alpine:3.19\nCMD [\"sh\"]\n"


def test_r10_detects_base_image_substitution():
    detections = detect_refactorings(R10_BEFORE, R10_AFTER)
    assert [d.refactoring_id for d in detections] == ["R10"]
    detection = detections[0]
    assert detection.refactoring_name == "Update Base Image"
    assert detection.instructions_before == (("FROM", "ubuntu:22.04"),)
    assert detection.instructions_after == (("FROM", "alpine:3.19"),)


def test_r10_detects_with_crlf_line_endings():
    detections = detect_refactorings(
        R10_BEFORE.replace("\n", "\r\n"), R10_AFTER.replace("\n", "\r\n")
    )
    assert [d.refactoring_id for d in detections] == ["R10"]


def test_r10_detected_despite_noise_in_other_instructions():
    # Granular evaluation: the entity substitution is R10 even when the
    # commit also edits a WORKDIR and a RUN.
    detections = detect_refactorings(
        "FROM ubuntu:22.04\nWORKDIR /app\nRUN echo hi\nCMD [\"sh\"]\n",
        "FROM alpine:3.19\nWORKDIR /src\nRUN echo hello\nCMD [\"sh\"]\n",
    )
    assert [d.refactoring_id for d in detections] == ["R10"]


def test_r10_reports_reverse_substitution_direction_judged_by_metrics():
    # Author's decision (Option A): the lighter/more-secure direction is
    # empirical, so the structural rule also reports alpine -> ubuntu; the
    # downstream metrics and the RF6 trade-off flag judge the direction.
    detections = detect_refactorings(R10_AFTER, R10_BEFORE)
    assert [d.refactoring_id for d in detections] == ["R10"]


def test_r10_and_r03_reported_together():
    # Non-exclusion: entity substitution + new ENV in one commit reports
    # both, in rule-registry order (R03 registered before R10).
    detections = detect_refactorings(
        "FROM ubuntu:22.04\nCMD [\"sh\"]\n",
        "FROM alpine:3.19\nENV MODE=prod\nCMD [\"sh\"]\n",
    )
    assert [d.refactoring_id for d in detections] == ["R03", "R10"]


def test_r10_not_triggered_when_alias_also_changes():
    # Entity substitution combined with a stage-alias change on the same
    # FROM is not a clean R10; the rule stays silent for that FROM.
    detections = detect_refactorings(
        "FROM ubuntu:22.04 AS build\nCMD [\"sh\"]\n",
        "FROM alpine:3.19 AS builder\nCMD [\"sh\"]\n",
    )
    assert detections == []


def test_r10_not_triggered_when_stage_count_differs():
    # A FROM added alongside the substitution changes the stage structure:
    # alignment is ambiguous (Extract/Inline Stage territory) — silent.
    detections = detect_refactorings(
        "FROM ubuntu:22.04\nCMD [\"sh\"]\n",
        "FROM golang:1.22 AS build\nRUN go build\nFROM alpine:3.19\nCMD [\"sh\"]\n",
    )
    assert detections == []


# --- R14 — Rename Image -----------------------------------------------------------

R14_BEFORE = (
    "FROM golang:1.22\n"
    "RUN go build -o /app ./cmd\n"
    "FROM alpine:3.19\n"
    "COPY --from=0 /app /app\n"
)
R14_AFTER = (
    "FROM golang:1.22 AS build\n"
    "RUN go build -o /app ./cmd\n"
    "FROM alpine:3.19\n"
    "COPY --from=build /app /app\n"
)


def test_r14_detects_naming_an_unnamed_stage():
    # Variant 1 (alias appears): eliminates the numeric --from=0 reference.
    # The COPY --from update is consequential noise, not part of the
    # detection (author's decision: FROM-only scope).
    detections = detect_refactorings(R14_BEFORE, R14_AFTER)
    assert [d.refactoring_id for d in detections] == ["R14"]
    detection = detections[0]
    assert detection.refactoring_name == "Rename Image"
    assert detection.instructions_before == (("FROM", "golang:1.22"),)
    assert detection.instructions_after == (("FROM", "golang:1.22 AS build"),)


def test_r14_detects_alias_rename():
    # Variant 2 (alias changes): direct equivalent of DRMiner's behaviour.
    detections = detect_refactorings(
        "FROM golang:1.22 AS build\nCMD [\"sh\"]\n",
        "FROM golang:1.22 AS builder\nCMD [\"sh\"]\n",
    )
    assert [d.refactoring_id for d in detections] == ["R14"]


def test_r14_detects_with_crlf_line_endings():
    detections = detect_refactorings(
        R14_BEFORE.replace("\n", "\r\n"), R14_AFTER.replace("\n", "\r\n")
    )
    assert [d.refactoring_id for d in detections] == ["R14"]


def test_r14_detected_despite_noise_in_other_instructions():
    # Granular evaluation: the alias appearing is R14 even when the commit
    # also edits a WORKDIR and a RUN.
    detections = detect_refactorings(
        "FROM golang:1.22\nWORKDIR /app\nRUN go build ./...\n",
        "FROM golang:1.22 AS build\nWORKDIR /src\nRUN go build -v ./...\n",
    )
    assert [d.refactoring_id for d in detections] == ["R14"]


def test_r14_not_triggered_when_alias_disappears():
    # Variant 3 (alias removed): reverse path, reintroduces numeric-
    # reference debt — ignored by design.
    assert detect_refactorings(R14_AFTER, R14_BEFORE) == []


def test_r14_not_triggered_when_image_also_changes():
    # Alias mutation combined with a tag change on the same FROM is neither
    # a clean R14 (image touched) nor R02 (alias touched): empty result.
    detections = detect_refactorings(
        "FROM node:18 AS build\nCMD [\"node\"]\n",
        "FROM node:20 AS builder\nCMD [\"node\"]\n",
    )
    assert detections == []


def test_r14_and_r02_reported_together():
    # Non-exclusion: one stage gains an alias while another gets a tag
    # bump — both reported, in rule-registry order.
    detections = detect_refactorings(
        "FROM golang:1.22\nRUN go build ./...\nFROM alpine:3.19\nCMD [\"sh\"]\n",
        "FROM golang:1.22 AS build\nRUN go build ./...\nFROM alpine:3.20\nCMD [\"sh\"]\n",
    )
    assert [d.refactoring_id for d in detections] == ["R02", "R14"]


# --- R12 — Remove RUN Instruction (mv command) ---------------------------------

# Mock pair mirroring the catalogue experiment for R12.
R12_BEFORE = """FROM alpine:3.20
WORKDIR /app
COPY app.conf /tmp/app.conf
RUN mkdir -p /app/config && mv /tmp/app.conf /app/config/app.conf
COPY entrypoint.sh /tmp/entrypoint.sh
RUN mkdir -p /app/bin && mv /tmp/entrypoint.sh /app/bin/entrypoint.sh
RUN chmod +x /app/bin/entrypoint.sh
CMD ["/app/bin/entrypoint.sh"]
"""
R12_AFTER = """FROM alpine:3.20
WORKDIR /app
COPY app.conf /app/config/app.conf
COPY entrypoint.sh /app/bin/entrypoint.sh
RUN chmod +x /app/bin/entrypoint.sh
CMD ["/app/bin/entrypoint.sh"]
"""


def test_r12_detects_removed_run_mv():
    detections = detect_refactorings(R12_BEFORE, R12_AFTER)
    assert [d.refactoring_id for d in detections] == ["R12"]
    detection = detections[0]
    assert detection.refactoring_name == "Remove RUN Instruction (mv command)"
    # both RUN mv instructions removed, both COPYs now landing directly
    assert len(detection.instructions_before) == 2
    assert len(detection.instructions_after) == 2
    assert detection.instructions_after[0] == ("COPY", "app.conf /app/config/app.conf")


def test_r12_detects_with_crlf_line_endings():
    detections = detect_refactorings(
        R12_BEFORE.replace("\n", "\r\n"), R12_AFTER.replace("\n", "\r\n")
    )
    assert [d.refactoring_id for d in detections] == ["R12"]


def test_r12_detects_a_bare_mv_without_mkdir():
    detections = detect_refactorings(
        "FROM alpine:3.20\nCOPY app.txt /tmp/app.txt\nRUN mv /tmp/app.txt /opt/app.txt\n",
        "FROM alpine:3.20\nCOPY app.txt /opt/app.txt\n",
    )
    assert [d.refactoring_id for d in detections] == ["R12"]


def test_r12_detected_despite_noise_in_other_instructions():
    # Granular evaluation: the relocation is R12 even when the commit also
    # edits a WORKDIR and a CMD.
    detections = detect_refactorings(
        "FROM alpine:3.20\nWORKDIR /app\nCOPY a.txt /tmp/a.txt\n"
        "RUN mv /tmp/a.txt /opt/a.txt\nCMD [\"sh\"]\n",
        "FROM alpine:3.20\nWORKDIR /src\nCOPY a.txt /opt/a.txt\nCMD [\"bash\"]\n",
    )
    assert [d.refactoring_id for d in detections] == ["R12"]


def test_r12_not_triggered_when_the_run_does_more_than_move():
    # The RUN also changes permissions, so its sole purpose is not the move.
    detections = detect_refactorings(
        "FROM alpine:3.20\nCOPY app.sh /tmp/app.sh\n"
        "RUN mv /tmp/app.sh /opt/app.sh && chmod +x /opt/app.sh\n",
        "FROM alpine:3.20\nCOPY app.sh /opt/app.sh\n",
    )
    assert detections == []


def test_r12_not_triggered_when_the_destination_did_not_move_into_the_copy():
    # The RUN mv disappeared but the COPY still lands on the temporary path:
    # the relocation was dropped, not folded into the transfer.
    detections = detect_refactorings(
        "FROM alpine:3.20\nCOPY app.txt /tmp/app.txt\nRUN mv /tmp/app.txt /opt/app.txt\n",
        "FROM alpine:3.20\nCOPY app.txt /tmp/app.txt\n",
    )
    assert detections == []


def test_r12_not_triggered_by_adding_a_run_mv():
    # Reverse path: introducing the extra layer is not a refactoring.
    assert detect_refactorings(R12_AFTER, R12_BEFORE) == []


# --- R13 — Update RUN Instruction ----------------------------------------------

# Mock pair mirroring the catalogue experiment for R13: same package set and
# versions, split across lines and sorted alphanumerically.
R13_BEFORE = """FROM alpine:3.20
RUN apk add --no-cache zlib=1.3.2-r0 curl=8.14.1-r2 bash=5.2.26-r0 git=2.45.4-r0 openssl=3.3.7-r0
"""
R13_AFTER = """FROM alpine:3.20
RUN apk add --no-cache \\
    bash=5.2.26-r0 \\
    curl=8.14.1-r2 \\
    git=2.45.4-r0 \\
    openssl=3.3.7-r0 \\
    zlib=1.3.2-r0
"""


def test_r13_detects_reformatted_and_sorted_run():
    detections = detect_refactorings(R13_BEFORE, R13_AFTER)
    assert [d.refactoring_id for d in detections] == ["R13"]
    detection = detections[0]
    assert detection.refactoring_name == "Update RUN Instruction"
    assert len(detection.instructions_before) == 1
    assert detection.instructions_before[0].instruction == "RUN"


def test_r13_detects_line_splitting_without_reordering():
    # Only the physical layout changes; the argument order is untouched.
    detections = detect_refactorings(
        "FROM alpine:3.20\nRUN apk add --no-cache bash=5.2.26-r0 curl=8.14.1-r2\n",
        "FROM alpine:3.20\nRUN apk add --no-cache \\\n    bash=5.2.26-r0 \\\n    curl=8.14.1-r2\n",
    )
    assert [d.refactoring_id for d in detections] == ["R13"]


def test_r13_detects_with_crlf_line_endings():
    detections = detect_refactorings(
        R13_BEFORE.replace("\n", "\r\n"), R13_AFTER.replace("\n", "\r\n")
    )
    assert [d.refactoring_id for d in detections] == ["R13"]


def test_r13_detected_despite_noise_in_other_instructions():
    detections = detect_refactorings(
        "FROM alpine:3.20\nWORKDIR /app\nRUN apk add --no-cache curl git\nCMD [\"sh\"]\n",
        "FROM alpine:3.20\nWORKDIR /src\nRUN apk add --no-cache git curl\nCMD [\"bash\"]\n",
    )
    assert [d.refactoring_id for d in detections] == ["R13"]


def test_r13_not_triggered_when_a_package_is_added():
    # The token multiset changes, so this is a content edit, not reformatting.
    detections = detect_refactorings(
        "FROM alpine:3.20\nRUN apk add --no-cache curl\n",
        "FROM alpine:3.20\nRUN apk add --no-cache \\\n    curl \\\n    git\n",
    )
    assert detections == []


def test_r13_not_triggered_when_a_version_changes():
    detections = detect_refactorings(
        "FROM alpine:3.20\nRUN apk add --no-cache curl=8.14.1-r2\n",
        "FROM alpine:3.20\nRUN apk add --no-cache curl=8.14.2-r0\n",
    )
    assert detections == []


def test_r13_not_triggered_when_the_run_count_changes():
    # Fewer RUN instructions is consolidation or removal territory.
    detections = detect_refactorings(
        "FROM alpine:3.20\nRUN echo a\nRUN echo b\n",
        "FROM alpine:3.20\nRUN echo a && echo b\n",
    )
    assert "R13" not in [d.refactoring_id for d in detections]


# --- R07 — Sort Instructions ----------------------------------------------------

# Mock pair mirroring the catalogue experiment for R07: identical instructions,
# rearranged so the package installations precede the file transfers.
R07_BEFORE = """FROM alpine:3.20
COPY app.txt /opt/app/app.txt
RUN apk add --no-cache curl=8.14.1-r2
COPY config.txt /opt/app/config.txt
RUN apk add --no-cache openssl=3.3.7-r0
"""
R07_AFTER = """FROM alpine:3.20
RUN apk add --no-cache curl=8.14.1-r2
RUN apk add --no-cache openssl=3.3.7-r0
COPY app.txt /opt/app/app.txt
COPY config.txt /opt/app/config.txt
"""


def test_r07_detects_cache_improving_reordering():
    detections = detect_refactorings(R07_BEFORE, R07_AFTER)
    assert [d.refactoring_id for d in detections] == ["R07"]
    detection = detections[0]
    assert detection.refactoring_name == "Sort Instructions"
    # the FROM did not move, so only the four rearranged instructions appear
    assert len(detection.instructions_before) == 4
    assert detection.instructions_before[0] == ("COPY", "app.txt /opt/app/app.txt")
    assert detection.instructions_after[0] == ("RUN", "apk add --no-cache curl=8.14.1-r2")


def test_r07_detects_with_crlf_line_endings():
    detections = detect_refactorings(
        R07_BEFORE.replace("\n", "\r\n"), R07_AFTER.replace("\n", "\r\n")
    )
    assert [d.refactoring_id for d in detections] == ["R07"]


def test_r07_not_triggered_by_cache_worsening_reordering():
    # Reverse path: moving a COPY ahead of the installation invalidates the
    # expensive layer on every source change.
    assert detect_refactorings(R07_AFTER, R07_BEFORE) == []


def test_r07_not_triggered_when_an_instruction_also_changes():
    # The instruction multiset differs, so this is not a pure rearrangement.
    detections = detect_refactorings(
        "FROM alpine:3.20\nCOPY app.txt /app.txt\nRUN apk add --no-cache curl\n",
        "FROM alpine:3.20\nRUN apk add --no-cache curl git\nCOPY app.txt /app.txt\n",
    )
    assert detections == []


def test_r07_not_triggered_by_reordering_without_cache_effect():
    # Both instructions are volatile transfers: swapping them changes nothing
    # about cache validity, so there is no refactoring to report.
    detections = detect_refactorings(
        "FROM alpine:3.20\nCOPY a.txt /a.txt\nCOPY b.txt /b.txt\n",
        "FROM alpine:3.20\nCOPY b.txt /b.txt\nCOPY a.txt /a.txt\n",
    )
    assert detections == []


def test_r07_not_triggered_when_order_is_unchanged():
    assert detect_refactorings(R07_AFTER, R07_AFTER) == []


# --- R06 — Inline Stage ---------------------------------------------------------

# Mock pair mirroring the catalogue experiment for R06: a builder stage that
# discards nothing is merged into the single stage that remains.
R06_BEFORE = """FROM alpine:3.20 AS builder
WORKDIR /app
COPY app.sh /app/app.sh
RUN chmod +x /app/app.sh

FROM alpine:3.20
WORKDIR /app
COPY --from=builder /app/app.sh /app/app.sh
CMD ["/app/app.sh"]
"""
R06_AFTER = """FROM alpine:3.20
WORKDIR /app
COPY app.sh /app/app.sh
RUN chmod +x /app/app.sh
CMD ["/app/app.sh"]
"""


def test_r06_detects_inlined_stage():
    detections = detect_refactorings(R06_BEFORE, R06_AFTER)
    assert [d.refactoring_id for d in detections] == ["R06"]
    detection = detections[0]
    assert detection.refactoring_name == "Inline Stage"
    # the COPY --from that consumed the stage, and the work it absorbed
    assert detection.instructions_before[0] == (
        "COPY",
        "--from=builder /app/app.sh /app/app.sh",
    )
    assert ("RUN", "chmod +x /app/app.sh") in detection.instructions_after


def test_r06_detects_with_crlf_line_endings():
    detections = detect_refactorings(
        R06_BEFORE.replace("\n", "\r\n"), R06_AFTER.replace("\n", "\r\n")
    )
    assert [d.refactoring_id for d in detections] == ["R06"]


def test_r06_detects_a_numeric_stage_reference():
    # An unnamed stage is referenced by its index.
    detections = detect_refactorings(
        "FROM alpine:3.20\nRUN echo build > /out.txt\n"
        "FROM alpine:3.20\nCOPY --from=0 /out.txt /out.txt\n",
        "FROM alpine:3.20\nRUN echo build > /out.txt\n",
    )
    assert [d.refactoring_id for d in detections] == ["R06"]


def test_r06_not_triggered_when_the_stage_work_vanished():
    # The stage and its instructions disappeared without being absorbed:
    # a deletion, not an inlining.
    detections = detect_refactorings(
        "FROM alpine:3.20 AS builder\nRUN echo build > /out.txt\n"
        "FROM alpine:3.20\nCOPY --from=builder /out.txt /out.txt\nCMD [\"sh\"]\n",
        "FROM alpine:3.20\nCMD [\"sh\"]\n",
    )
    assert detections == []


def test_r06_not_triggered_when_the_stage_is_still_consumed():
    # Stage count falls but the surviving build still reads from the stage.
    detections = detect_refactorings(
        "FROM alpine:3.20 AS builder\nRUN echo b > /out.txt\n"
        "FROM alpine:3.20 AS extra\nRUN echo e > /e.txt\n"
        "FROM alpine:3.20\nCOPY --from=builder /out.txt /out.txt\n",
        "FROM alpine:3.20 AS builder\nRUN echo b > /out.txt\n"
        "FROM alpine:3.20\nCOPY --from=builder /out.txt /out.txt\n",
    )
    assert "R06" not in [d.refactoring_id for d in detections]


def test_r06_not_triggered_by_extracting_a_stage():
    # Reverse path: going from one stage to two is Extract Stage, not Inline.
    assert "R06" not in [d.refactoring_id for d in detect_refactorings(R06_AFTER, R06_BEFORE)]


# --- R05 — Extract Stage --------------------------------------------------------

# Mock pair mirroring the catalogue experiment for R05: a single-stage build
# is split so the toolchain stays behind and only the artifact crosses over.
R05_BEFORE = """FROM rust:1.78
WORKDIR /usr/src/myapp
RUN cargo new --bin testapp
RUN cargo build --release
CMD ["./target/release/testapp"]
"""
R05_AFTER = """FROM rust:1.78 AS builder
WORKDIR /usr/src/myapp
RUN cargo new --bin testapp
RUN cargo build --release

FROM alpine:3.20
WORKDIR /app
COPY --from=builder /usr/src/myapp/target/release/testapp .
CMD ["./testapp"]
"""


def test_r05_detects_extracted_stage():
    detections = detect_refactorings(R05_BEFORE, R05_AFTER)
    assert [d.refactoring_id for d in detections] == ["R05"]
    detection = detections[0]
    assert detection.refactoring_name == "Extract Stage"
    # the build work that moved into the new stage
    assert ("RUN", "cargo build --release") in detection.instructions_before
    # the COPY --from that now brings the artifact across
    assert detection.instructions_after[0].instruction == "COPY"
    assert "--from=builder" in detection.instructions_after[0].value


def test_r05_detects_with_crlf_line_endings():
    detections = detect_refactorings(
        R05_BEFORE.replace("\n", "\r\n"), R05_AFTER.replace("\n", "\r\n")
    )
    assert [d.refactoring_id for d in detections] == ["R05"]


def test_r05_not_triggered_when_the_new_stage_does_new_work():
    # A stage was added, but none of its instructions existed before: it is
    # new work rather than an extraction of the existing build.
    detections = detect_refactorings(
        "FROM alpine:3.20\nRUN echo app > /app.txt\nCMD [\"sh\"]\n",
        "FROM alpine:3.20 AS docs\nRUN echo docs > /docs.txt\n"
        "FROM alpine:3.20\nRUN echo app > /app.txt\n"
        "COPY --from=docs /docs.txt /docs.txt\nCMD [\"sh\"]\n",
    )
    assert "R05" not in [d.refactoring_id for d in detections]


def test_r05_not_triggered_when_nothing_consumes_the_new_stage():
    # The stage count rises but no COPY --from reads from the added stage.
    detections = detect_refactorings(
        "FROM alpine:3.20\nRUN echo a > /a.txt\n",
        "FROM golang:1.22 AS build\nRUN go version\nFROM alpine:3.20\nRUN echo a > /a.txt\n",
    )
    assert "R05" not in [d.refactoring_id for d in detections]


def test_r05_not_triggered_by_inlining_a_stage():
    # Reverse path: collapsing two stages into one is R06, not R05.
    assert "R05" not in [d.refactoring_id for d in detect_refactorings(R05_AFTER, R05_BEFORE)]


# --- R11 — Move Stage -----------------------------------------------------------

# Mock pair mirroring the catalogue experiment for R11. Only the main Dockerfile
# is compared: the extracted one is a second file the pipeline never sees, and
# the refactoring is visible here as a stage whose body left and whose FROM now
# names the image that build produces.
R11_BEFORE = """FROM alpine:3.20 AS builder
WORKDIR /build
COPY app.txt /build/app.txt
RUN cp /build/app.txt /build/artifact.txt

FROM alpine:3.20
WORKDIR /app
COPY --from=builder /build/artifact.txt /app/artifact.txt
CMD ["cat", "/app/artifact.txt"]
"""
R11_AFTER = """FROM r11-builder:1.0 AS builder

FROM alpine:3.20
WORKDIR /app
COPY --from=builder /build/artifact.txt /app/artifact.txt
CMD ["cat", "/app/artifact.txt"]
"""


def test_r11_detects_moved_stage():
    detections = detect_refactorings(R11_BEFORE, R11_AFTER)
    assert "R11" in [d.refactoring_id for d in detections]
    detection = next(d for d in detections if d.refactoring_id == "R11")
    assert detection.refactoring_name == "Move Stage"
    # the body that left the file
    assert ("RUN", "cp /build/app.txt /build/artifact.txt") in detection.instructions_before
    # the emptied stage now naming the externally built image
    assert detection.instructions_after == (("FROM", "r11-builder:1.0 AS builder"),)


def test_r11_detects_with_crlf_line_endings():
    detections = detect_refactorings(
        R11_BEFORE.replace("\n", "\r\n"), R11_AFTER.replace("\n", "\r\n")
    )
    assert "R11" in [d.refactoring_id for d in detections]


def test_r11_leaves_the_stage_count_unchanged():
    # What separates Move Stage from Extract (R05) and Inline (R06).
    detections = detect_refactorings(R11_BEFORE, R11_AFTER)
    reported = [d.refactoring_id for d in detections]
    assert "R05" not in reported and "R06" not in reported


def test_r11_not_triggered_when_the_stage_body_is_merely_deleted():
    # Emptied but still on the same base: the work was deleted, not moved out.
    detections = detect_refactorings(
        R11_BEFORE,
        "FROM alpine:3.20 AS builder\n\nFROM alpine:3.20\nWORKDIR /app\n"
        "COPY --from=builder /build/artifact.txt /app/artifact.txt\n"
        "CMD [\"cat\", \"/app/artifact.txt\"]\n",
    )
    assert "R11" not in [d.refactoring_id for d in detections]


def test_r11_not_triggered_when_nothing_consumes_the_stage():
    # The stage was emptied and re-based but nothing reads from it any more.
    detections = detect_refactorings(
        "FROM alpine:3.20 AS builder\nRUN echo a > /a.txt\nFROM alpine:3.20\nCMD [\"sh\"]\n",
        "FROM r11-builder:1.0 AS builder\nFROM alpine:3.20\nCMD [\"sh\"]\n",
    )
    assert "R11" not in [d.refactoring_id for d in detections]


def test_r11_not_triggered_by_bringing_the_stage_back():
    # Reverse path: restoring the body into the Dockerfile is not a move.
    assert "R11" not in [d.refactoring_id for d in detect_refactorings(R11_AFTER, R11_BEFORE)]


# --- R09 — Extract RUN Instructions ---------------------------------------------

# Mock pair mirroring the catalogue experiment for R09. The script itself is a
# file the pipeline never sees; what is compared is the Dockerfile, where the
# chained shell commands give way to a COPY of the script and a call to it.
R09_BEFORE = """FROM alpine:3.20
WORKDIR /app
COPY app.txt /app/app.txt
RUN mkdir -p /app/data && cp /app/app.txt /app/data/app.txt && chmod -R 755 /app/data
CMD ["sh", "-c", "cat /app/data/app.txt"]
"""
R09_AFTER = """FROM alpine:3.20
WORKDIR /app
COPY app.txt /app/app.txt
COPY setup.sh /app/setup.sh
RUN /app/setup.sh
CMD ["sh", "-c", "cat /app/data/app.txt"]
"""


def test_r09_detects_run_extracted_into_a_script():
    detections = detect_refactorings(R09_BEFORE, R09_AFTER)
    assert [d.refactoring_id for d in detections] == ["R09"]
    detection = detections[0]
    assert detection.refactoring_name == "Extract RUN Instructions"
    # the shell sequence that left the Dockerfile
    assert detection.instructions_before == (
        ("RUN", "mkdir -p /app/data && cp /app/app.txt /app/data/app.txt && chmod -R 755 /app/data"),
    )
    # the script arriving, and the call that replaced the sequence
    assert detection.instructions_after == (
        ("COPY", "setup.sh /app/setup.sh"),
        ("RUN", "/app/setup.sh"),
    )


def test_r09_detects_with_crlf_line_endings():
    detections = detect_refactorings(
        R09_BEFORE.replace("\n", "\r\n"), R09_AFTER.replace("\n", "\r\n")
    )
    assert [d.refactoring_id for d in detections] == ["R09"]


def test_r09_detects_when_the_script_lands_in_a_directory():
    # "COPY setup.sh /app/" gives the script the source's file name.
    detections = detect_refactorings(
        R09_BEFORE,
        R09_AFTER.replace("COPY setup.sh /app/setup.sh", "COPY setup.sh /app/").replace(
            "RUN /app/setup.sh", "RUN sh setup.sh"
        ),
    )
    assert "R09" in [d.refactoring_id for d in detections]


def test_r09_ignores_unrelated_changed_instructions():
    # Granularity: a WORKDIR edited in the same commit is noise for this rule.
    detections = detect_refactorings(
        R09_BEFORE, R09_AFTER.replace("WORKDIR /app", "WORKDIR /srv/app")
    )
    assert "R09" in [d.refactoring_id for d in detections]


def test_r09_not_triggered_when_the_script_is_never_executed():
    # A script copied in but only made executable is prepared, not run: the
    # path stands as an argument to chmod, never in command position.
    detections = detect_refactorings(
        R09_BEFORE, R09_AFTER.replace("RUN /app/setup.sh", "RUN chmod +x /app/setup.sh")
    )
    assert "R09" not in [d.refactoring_id for d in detections]


def test_r09_not_triggered_when_the_script_only_moves_destination():
    # A script already in the image, re-copied to another path, is not newly
    # extracted work — the guard that keeps R09 off the R12 scenario.
    detections = detect_refactorings(
        "FROM alpine:3.20\nCOPY entrypoint.sh /tmp/entrypoint.sh\n"
        "RUN mkdir -p /app/bin && mv /tmp/entrypoint.sh /app/bin/entrypoint.sh\n"
        "RUN /app/bin/entrypoint.sh\n",
        "FROM alpine:3.20\nCOPY entrypoint.sh /app/bin/entrypoint.sh\n"
        "RUN /app/bin/entrypoint.sh\n",
    )
    assert "R09" not in [d.refactoring_id for d in detections]


def test_r09_not_triggered_when_no_shell_work_leaves_the_file():
    # A script added on top of the existing RUN is new functionality, not an
    # extraction: the shell commands are still in the Dockerfile.
    detections = detect_refactorings(
        R09_BEFORE,
        R09_BEFORE.replace(
            "CMD", "COPY extra.sh /app/extra.sh\nRUN /app/extra.sh\nCMD"
        ),
    )
    assert "R09" not in [d.refactoring_id for d in detections]


def test_r09_not_triggered_when_the_copied_file_is_not_a_script():
    detections = detect_refactorings(
        R09_BEFORE,
        R09_AFTER.replace("COPY setup.sh /app/setup.sh", "COPY setup.bin /app/setup.bin")
        .replace("RUN /app/setup.sh", "RUN /app/setup.bin"),
    )
    assert "R09" not in [d.refactoring_id for d in detections]


def test_r09_not_triggered_by_inlining_the_script_back():
    # Reverse path: the script COPY disappears instead of appearing.
    assert "R09" not in [d.refactoring_id for d in detect_refactorings(R09_AFTER, R09_BEFORE)]


# --- Negative cases: MUST return an empty result -------------------------------


def test_identical_dockerfiles_yield_empty_result():
    assert detect_refactorings(R02_AFTER, R02_AFTER) == []


def test_r02_not_triggered_by_base_image_name_change():
    # ubuntu -> alpine changes the repository name: R10, never R02.
    detections = detect_refactorings(
        "FROM ubuntu:22.04\nCMD [\"sh\"]\n", "FROM alpine:3.19\nCMD [\"sh\"]\n"
    )
    assert "R02" not in [d.refactoring_id for d in detections]


def test_r02_entity_preservation_defers_full_substitution_to_r10():
    # Name AND tag change together ('ubuntu' [= ubuntu:latest] -> 'alpine:3.18'):
    # the base-image entity is not preserved, so this is never a tag
    # refactoring (R02) — it is reported by the R10 rule instead.
    detections = detect_refactorings(
        "FROM ubuntu\nCMD [\"sh\"]\n", "FROM alpine:3.18\nCMD [\"sh\"]\n"
    )
    assert [d.refactoring_id for d in detections] == ["R10"]


def test_r02_not_triggered_by_unpinning_to_latest():
    # Directional rule: moving TO latest (explicit or by dropping the tag)
    # reintroduces the DL3007 smell — the reverse path is not a refactoring.
    assert detect_refactorings(
        "FROM ubuntu:22.04\nCMD [\"sh\"]\n", "FROM ubuntu:latest\nCMD [\"sh\"]\n"
    ) == []
    assert detect_refactorings(
        "FROM ubuntu:22.04\nCMD [\"sh\"]\n", "FROM ubuntu\nCMD [\"sh\"]\n"
    ) == []


def test_r02_not_triggered_by_stage_alias_change():
    detections = detect_refactorings(
        "FROM node:18 AS build\nCMD [\"node\"]\n",
        "FROM node:20 AS builder\nCMD [\"node\"]\n",
    )
    assert "R02" not in [d.refactoring_id for d in detections]


def test_r02_not_confused_by_registry_port():
    # The ':5000' is a registry port, not a tag: the repository name is what
    # actually changed, so this is an entity substitution (R10), never R02.
    detections = detect_refactorings(
        "FROM registry:5000/app:1.0\nCMD [\"sh\"]\n",
        "FROM registry:5000/other:1.0\nCMD [\"sh\"]\n",
    )
    assert [d.refactoring_id for d in detections] == ["R10"]
