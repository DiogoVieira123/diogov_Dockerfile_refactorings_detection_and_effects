"""Detection Engine — analytical core of the pipeline (Chapter 5, Section 5.4).

Receives the two Dockerfile strings from the VCS Connector and determines
whether the structural change between them constitutes a recognised
refactoring type (RF2). Each Dockerfile is decomposed by dockerfile-parse
(validated in Experiment 5) into an ordered list of logical instruction
objects, so multi-line RUN instructions joined by backslash continuations are
compared as single logical units.

Each detection rule is an independent function registered in a central rule
registry (RNF3), and obeys three architecture laws:

1. Directional mechanical rules — each rule detects strictly the
   transformation direction its ID's definition in the Extended Catalogue
   mandates. The reverse path of a one-direction refactoring introduces
   technical debt or smells and is ignored by design (empty result). Where
   the catalogue defines complementary directions as distinct refactorings,
   each direction gets its own dedicated rule and ID.
2. Granular evaluation — each rule extracts its own refactoring from the
   instruction subset it concerns, ignoring changes to other instructions
   in the same commit, catalogued or not.
3. Non-exclusion (design chapter, Detection Engine, Challenges) — when a
   single commit satisfies multiple detection criteria, ALL identified
   refactorings are recorded into a cumulative result list. Where a
   deterministic resolution is needed, the engine relies strictly on the
   rule-registry indexing order, decoupled from the quality dimensions.

A negative case — no supported refactoring between the two versions — yields
an empty list, never a partial or speculative match.
"""

import io
import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable, NamedTuple, Optional

from dockerfile_parse import DockerfileParser


class DockerfileParseError(Exception):
    """Dockerfile content could not be parsed into logical instructions.

    RNF4: parsing failures surface as this specific exception instead of the
    raw error of the underlying library, so the pipeline can distinguish
    malformed content from a build or daemon failure.
    """


class Instruction(NamedTuple):
    """One logical Dockerfile instruction (multi-line RUNs already joined)."""

    instruction: str  # e.g. "FROM", "RUN" (upper-case, per dockerfile-parse)
    value: str  # argument string with continuations resolved


@dataclass(frozen=True)
class DetectionResult:
    """A detected refactoring: its catalogue identifier and the instructions involved.

    RF3: the identifier is a label attached to the detection and carries no
    quality expectation. No impact field exists here by design — the metric
    deltas are computed independently by the Performance Analyzer and the Data
    Extractor from the two Dockerfile states.
    """

    refactoring_id: str  # formal catalogue identifier, R01–R14
    refactoring_name: str  # e.g. "Update Base Image TAG"
    instructions_before: tuple  # involved Instruction objects in version A
    instructions_after: tuple  # involved Instruction objects in version B


def parse_instructions(dockerfile_content: str) -> list:
    """Parse Dockerfile text into its logical instruction list.

    CRLF line endings are normalised to LF before parsing: blob content
    retrieved by the VCS Connector reflects whatever was committed (see
    IMPLEMENTATION_LOG, VCS Connector entry), so the parser must not assume
    LF-only input. Comments are excluded — they carry no structural meaning
    for detection. An in-memory fileobj keeps dockerfile-parse from writing
    a Dockerfile to the working directory (its default behaviour).

    Raises:
        DockerfileParseError: the content is not text, or dockerfile-parse
            cannot decompose it into logical instructions (RNF4).
    """
    if not isinstance(dockerfile_content, str):
        raise DockerfileParseError(
            f"Dockerfile content must be a string, got "
            f"{type(dockerfile_content).__name__}."
        )
    try:
        parser = DockerfileParser(fileobj=io.BytesIO())
        parser.content = dockerfile_content.replace("\r\n", "\n")
        structure = parser.structure
    except Exception as exc:  # noqa: BLE001 — any parser failure is malformed content
        raise DockerfileParseError(
            f"Dockerfile content could not be parsed into logical "
            f"instructions: {exc}"
        ) from exc

    return [
        Instruction(entry["instruction"], entry["value"])
        for entry in structure
        if entry["instruction"] != "COMMENT"
    ]


# --- Rule registry (RNF3) ---------------------------------------------------

_RuleFunction = Callable[[list, list], Optional[DetectionResult]]
_RULES: list = []  # rule functions, in registry indexing order


def rule(function: _RuleFunction) -> _RuleFunction:
    """Register a detection rule; rules stay independent of each other.

    The registry indexing order — the order the rules appear in this module —
    is the only deterministic ordering the engine applies to its results.
    """
    _RULES.append(function)
    return function


def detect_refactorings(dockerfile_a: str, dockerfile_b: str) -> list:
    """Run every registered rule over the two versions.

    Returns ALL detected refactorings (non-exclusion principle), in rule
    registry indexing order, or an empty list when no supported refactoring
    is recognised. No priority between quality dimensions is applied.
    """
    instructions_a = parse_instructions(dockerfile_a)
    instructions_b = parse_instructions(dockerfile_b)
    detections = []
    for rule_function in _RULES:
        detection = rule_function(instructions_a, instructions_b)
        if detection is not None:
            detections.append(detection)
    return detections


# --- FROM value helpers ------------------------------------------------------


class _FromParts(NamedTuple):
    """Decomposed FROM argument: flags, image name, tag, digest, stage alias."""

    flags: tuple  # e.g. ("--platform=$BUILDPLATFORM",)
    name: str  # repository name, e.g. "ubuntu" or "registry:5000/app"
    tag: str  # explicit tag, or "latest" when omitted (Docker's default)
    digest: str  # "@sha256:..." pin, or "" when absent
    alias: str  # "AS <alias>" stage name, or "" when absent


def _parse_from_value(value: str) -> _FromParts:
    tokens = value.split()
    flags = tuple(token for token in tokens if token.startswith("--"))
    rest = [token for token in tokens if not token.startswith("--")]
    reference = rest[0] if rest else ""
    alias = rest[2] if len(rest) >= 3 and rest[1].upper() == "AS" else ""

    digest = ""
    if "@" in reference:
        reference, digest = reference.split("@", 1)
    # The tag separator is a ':' after the last '/', so registry ports
    # (e.g. registry:5000/app) are not mistaken for tags.
    name, tag = reference, "latest"
    last_colon = reference.rfind(":")
    if last_colon > reference.rfind("/"):
        name, tag = reference[:last_colon], reference[last_colon + 1 :]
    return _FromParts(flags=flags, name=name, tag=tag, digest=digest, alias=alias)


def _from_instructions(instructions: list) -> list:
    return [entry for entry in instructions if entry.instruction == "FROM"]


_SHELL_SEPARATORS = re.compile(r"&&|\|\||;")


def _shell_segments(value: str) -> list:
    """Command segments of a RUN body, whitespace-normalised.

    Consolidating RUN instructions chains what were separate commands with
    ``&&`` (or ``;`` / ``||``), so splitting on those operators recovers the
    commands the separate instructions used to hold. Whitespace is normalised
    because a multi-line RUN joined by backslash continuations keeps the
    indentation of the physical lines inside its argument string.
    """
    return [" ".join(part.split()) for part in _SHELL_SEPARATORS.split(value) if part.split()]


_FILE_TRANSFER_INSTRUCTIONS = ("COPY", "ADD")


class Stage(NamedTuple):
    """One build stage: the FROM that opens it and the instructions it holds."""

    index: int  # position among the stages, which is how an unnamed stage is referenced
    reference: str  # image reference of the FROM, e.g. "alpine:3.20"
    alias: str  # name given by "AS <alias>", or "" when the stage is unnamed
    instructions: tuple  # the stage's instructions, the opening FROM excluded

    @property
    def identity(self) -> str:
        """How a COPY --from names this stage: its alias, or its index."""
        return self.alias.lower() if self.alias else str(self.index)


def _stages(instructions: list) -> list:
    """Decompose an instruction list into build stages.

    Shared by every stage-level rule. Instructions appearing before the first
    FROM (a top-level ARG, for instance) belong to no stage and are skipped,
    since they are not part of any stage's body.
    """
    stages, bodies = [], []
    for entry in instructions:
        if entry.instruction == "FROM":
            parts = _parse_from_value(entry.value)
            reference = parts.name + (f":{parts.tag}" if parts.tag else "")
            stages.append([len(stages), reference, parts.alias])
            bodies.append([])
        elif stages:
            bodies[-1].append(entry)
    return [
        Stage(index=index, reference=reference, alias=alias, instructions=tuple(body))
        for (index, reference, alias), body in zip(stages, bodies)
    ]


def _stage_reference_of(entry) -> Optional[str]:
    """The stage a COPY or ADD reads from via ``--from=``, or None."""
    if entry.instruction not in _FILE_TRANSFER_INSTRUCTIONS:
        return None
    for token in entry.value.split():
        if token.startswith("--from="):
            return token.split("=", 1)[1].lower()
    return None

# Dependency installation: the stable, resource-intensive step whose cache
# Zhu et al. show is worth preserving by placing it before volatile steps.
_PACKAGE_INSTALL = re.compile(
    r"\b(?:apt-get\s+install|apt\s+install|apk\s+add|yum\s+install|dnf\s+install"
    r"|pip3?\s+install|npm\s+(?:install|ci)|yarn\s+install|gem\s+install"
    r"|pacman\s+-S|zypper\s+install)\b"
)


def _cache_class(entry) -> Optional[str]:
    """Classify an instruction for cache-ordering purposes.

    The proxy is the one the refactoring itself implies: installing
    dependencies is the stable and expensive step, while copying project
    files is what changes on almost every commit. Instructions that are
    neither carry no ordering signal and are ignored.
    """
    if entry.instruction == "RUN" and _PACKAGE_INSTALL.search(entry.value):
        return "stable"
    if entry.instruction in _FILE_TRANSFER_INSTRUCTIONS:
        return "volatile"
    return None


def _cache_inversions(instructions: list) -> int:
    """Count volatile steps standing before stable ones.

    Each such pair invalidates the cache of an expensive step whenever the
    volatile file changes, so a lower count is a better cache ordering.
    """
    classes = [c for c in (_cache_class(e) for e in instructions) if c]
    return sum(
        1
        for index, current in enumerate(classes)
        if current == "volatile"
        for later in classes[index + 1:]
        if later == "stable"
    )
# mkdir only prepares the directory the move lands in; COPY creates it on its
# own, so a RUN combining mkdir with mv is still solely a relocation.
_MOVE_COMPANION_COMMANDS = {"mkdir"}


def _transfer_operands(value: str):
    """(sources, destination) of a COPY or ADD, or None when malformed.

    Flags such as ``--from`` or ``--chown`` are skipped; the destination is
    the last operand, as the Dockerfile syntax defines.
    """
    tokens = [token for token in value.split() if not token.startswith("--")]
    if len(tokens) < 2:
        return None
    return tuple(tokens[:-1]), tokens[-1]


def _move_relocations(value: str):
    """(source, destination) of every mv in a RUN body, or None.

    Returns None when the RUN does anything beyond relocating files, so that
    only instructions whose sole purpose is the move are considered.
    """
    relocations = []
    for segment in _shell_segments(value):
        tokens = segment.split()
        if not tokens:
            continue
        command = tokens[0]
        if command == "mv":
            operands = [token for token in tokens[1:] if not token.startswith("-")]
            if len(operands) != 2:
                return None  # multi-source move: not a single relocation
            relocations.append((operands[0], operands[1]))
        elif command not in _MOVE_COMPANION_COMMANDS:
            return None  # the RUN does more than move files
    return relocations or None


def _values_of(instructions: list, keyword: str) -> list:
    return [entry.value for entry in instructions if entry.instruction == keyword]


def _env_names(value: str) -> set:
    """Variable names declared by one ENV argument string.

    Handles both forms: ``ENV A=1 B=2`` (one or more ``key=value`` pairs)
    and the legacy single-variable form ``ENV MODE dev``.
    """
    if "=" in value:
        return {token.split("=", 1)[0] for token in value.split() if "=" in token}
    tokens = value.split()
    return {tokens[0]} if tokens else set()


def _arg_name(value: str) -> str:
    """Identifier declared by one ARG argument string (``NAME[=default]``)."""
    return value.split("=", 1)[0].strip()


# A shell script is what a RUN body is extracted into, so only these suffixes
# make a transferred file a candidate carrier of extracted instructions.
_SCRIPT_SUFFIXES = (".sh", ".bash")


def _script_destinations(entry) -> tuple:
    """Paths a COPY or ADD gives to the shell scripts it brings into the image.

    A destination naming a directory keeps the source file name, so both forms
    (``COPY setup.sh /app/setup.sh`` and ``COPY setup.sh /app/``) resolve to
    the path the RUN would invoke.
    """
    operands = _transfer_operands(entry.value)
    if operands is None:
        return ()
    sources, destination = operands
    target = destination.strip("[]\"',")
    paths = []
    for source in sources:
        name = source.strip("[]\"',")
        if not name.lower().endswith(_SCRIPT_SUFFIXES):
            continue
        if target.endswith("/") or len(sources) > 1:
            paths.append(target.rstrip("/") + "/" + name.rsplit("/", 1)[-1])
        else:
            paths.append(target)
    return tuple(paths)


_SHELL_INTERPRETERS = {"sh", "bash", "ash", "dash", ".", "source"}


def _invokes_script(value: str, path: str) -> bool:
    """True when a RUN body executes the script living at ``path``.

    The script must stand where a command stands: either as a segment's own
    command — its ``/app/setup.sh`` and ``./setup.sh`` forms are both
    recognised — or as the file an interpreter is handed (``sh setup.sh``). A
    path merely passed to another command, as in ``chmod +x /app/setup.sh``,
    prepares the script but does not run it, and is not an invocation.
    """
    script = path.rsplit("/", 1)[-1]

    def names_script(token: str) -> bool:
        cleaned = token.strip("\"';")
        if cleaned.startswith("./"):
            cleaned = cleaned[2:]
        return cleaned.rsplit("/", 1)[-1] == script

    for segment in _shell_segments(value):
        tokens = segment.split()
        if not tokens:
            continue
        if names_script(tokens[0]):
            return True
        if tokens[0] in _SHELL_INTERPRETERS and any(
            names_script(token) for token in tokens[1:] if not token.startswith("-")
        ):
            return True
    return False


_URL_PREFIXES = ("http://", "https://", "ftp://")
_ARCHIVE_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")


def _uses_add_only_capability(value: str) -> bool:
    """True when an ADD argument string relies on a capability COPY lacks.

    A source that is a remote URL (ADD downloads it; COPY cannot) or an
    auto-extractable local archive (ADD unpacks it into the destination;
    COPY copies the file as-is) makes the keyword swap behaviour-changing.
    Per the catalogue ("Replace ADD with COPY where the implicit behaviours
    are not needed") and Fowler's definition of refactoring as
    behaviour-preserving, such an ADD is not eligible for R08.
    """
    tokens = [token for token in value.split() if not token.startswith("--")]
    sources = tokens[:-1]  # the last token is the destination
    for source in sources:
        cleaned = source.strip("[]\"',").lower()
        if cleaned.startswith(_URL_PREFIXES) or cleaned.endswith(_ARCHIVE_SUFFIXES):
            return True
    return False


# --- Detection rules ---------------------------------------------------------


@rule
def detect_inline_run_instructions(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R01 — Inline RUN Instructions.

    Granular, directional rule over the RUN subset only: consecutive RUN
    instructions are consolidated into fewer instructions, which is the fix
    for the DL3059 smell. The count of RUN instructions must therefore fall;
    splitting one RUN into several is the reverse path and is not reported.

    Content preservation check (design chapter, third challenge): a falling
    RUN count is ambiguous on its own, because it may be a consolidation or a
    plain deletion. The check looks for positive evidence of merging: the
    commands of each state are recovered by splitting the RUN bodies on the
    shell operators, and a surviving RUN counts as merged when it carries
    commands that used to live in two or more separate RUN instructions.

    The check is deliberately permissive about commands that disappear.
    Real commits routinely combine inlining with cleanup, dropping an
    adjacent command in the same change, and requiring every command to
    survive would miss those. What it does not tolerate is the absence of
    merging altogether: without a surviving RUN that joins commands from two
    or more previous ones, the change is a plain deletion and is not reported.
    """
    runs_a = _values_of(instructions_a, "RUN")
    runs_b = _values_of(instructions_b, "RUN")

    # Directional: consolidation reduces the number of RUN instructions.
    if not runs_a or len(runs_a) <= len(runs_b):
        return None

    # Trace every command back to the RUN instructions that used to hold it.
    segment_origin = {}
    for index, value in enumerate(runs_a):
        for segment in _shell_segments(value):
            segment_origin.setdefault(segment, set()).add(index)

    # A surviving RUN is a merge when its commands come from >= 2 previous RUNs.
    merged_after = []
    merged_origins = set()
    for value in runs_b:
        origins = set()
        for segment in _shell_segments(value):
            origins |= segment_origin.get(segment, set())
        if len(origins) >= 2:
            merged_after.append(Instruction("RUN", value))
            merged_origins |= origins

    if not merged_after:
        return None  # no merging took place: deletion, not consolidation

    merged_before = [Instruction("RUN", runs_a[i]) for i in sorted(merged_origins)]

    return DetectionResult(
        refactoring_id="R01",
        refactoring_name="Inline RUN Instructions",
        instructions_before=tuple(merged_before),
        instructions_after=tuple(merged_after),
    )


@rule
def detect_update_base_image_tag(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R02 — Update Base Image TAG.

    Instructions are evaluated in isolation, per instruction: the rule looks
    only at the FROM instructions, aligned by stage position, and reports
    every one that is a tag-only update. Two conditions must hold for each
    reported FROM:

    1. Entity preservation — the base image entity is exactly the same
       before and after: identical repository name, digest, platform flags,
       and stage alias. A changed repository name (e.g. ``ubuntu`` →
       ``alpine:3.18``) is a full base-image substitution, which is
       conceptually a different refactoring (future R10), never R02.
    2. Directional tag update — the tag differs AND the destination tag is
       pinned (not "latest"). An omitted tag counts as "latest", Docker's
       default, so pinning ``ubuntu`` → ``ubuntu:22.04`` qualifies, and a
       pinned→pinned version bump (``ubuntu:20.04`` → ``ubuntu:22.04``) is
       a legitimate tag update (author's decision, 2026-07-05). The reverse
       direction — unpinning to ``latest`` or dropping the tag — reintroduces
       the DL3007 smell and is ignored by design (mechanical directional
       rule): it yields an empty result.

    Changes to any other instruction in the file — catalogued or not — are
    ignored by this rule; each rule extracts its own refactoring from the
    commit independently. When the two versions have a different number of
    FROMs, stage alignment is ambiguous (Extract/Inline Stage territory) and
    the rule stays silent rather than guessing.
    """
    froms_a = _from_instructions(instructions_a)
    froms_b = _from_instructions(instructions_b)
    if not froms_a or len(froms_a) != len(froms_b):
        return None

    changed_before = []
    changed_after = []
    for before, after in zip(froms_a, froms_b):
        if before == after:
            continue
        parts_before = _parse_from_value(before.value)
        parts_after = _parse_from_value(after.value)
        entity_preserved = (
            parts_before.name == parts_after.name
            and parts_before.digest == parts_after.digest
            and parts_before.flags == parts_after.flags
            and parts_before.alias == parts_after.alias
        )
        directional_tag_update = (
            parts_before.tag != parts_after.tag and parts_after.tag != "latest"
        )
        if entity_preserved and directional_tag_update:
            changed_before.append(before)
            changed_after.append(after)

    if not changed_before:
        return None

    return DetectionResult(
        refactoring_id="R02",
        refactoring_name="Update Base Image TAG",
        instructions_before=tuple(changed_before),
        instructions_after=tuple(changed_after),
    )


@rule
def detect_replace_add_with_copy(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R08 — Replace ADD with COPY.

    Granular, per-instruction evaluation over the ADD/COPY subset only:
    an ADD is reported as replaced when its exact argument string (sources
    and destination byte-identical) disappears from the ADDs and appears
    among the COPYs of the after version — the refactoring swaps the
    keyword, never the arguments. Changes to any other instruction in the
    commit are ignored.

    The comparison is multiset-based, so a COPY with the same arguments
    that already existed before does not create a false positive, an ADD
    that vanishes without a corresponding new COPY is a deletion rather
    than a refactoring, and the reverse swap (COPY to ADD, which
    reintroduces the DL3020 smell) is never reported.

    Behaviour-preservation guard: an ADD whose source is a remote URL or an
    auto-extractable archive uses a capability COPY lacks, so swapping the
    keyword would change the build result — not a refactoring, ignored.
    """
    adds_a = _values_of(instructions_a, "ADD")
    adds_b = Counter(_values_of(instructions_b, "ADD"))
    copies_a = Counter(_values_of(instructions_a, "COPY"))
    copies_b = Counter(_values_of(instructions_b, "COPY"))

    # For each argument string, the number of replacements is bounded both
    # by the ADDs that disappeared and by the COPYs that appeared.
    replacement_budget = {}
    for value in set(adds_a):
        if _uses_add_only_capability(value):
            continue
        removed_adds = adds_a.count(value) - adds_b[value]
        gained_copies = copies_b[value] - copies_a[value]
        replacement_budget[value] = min(removed_adds, gained_copies)

    changed_before = []
    changed_after = []
    for value in adds_a:  # original order of the ADDs in version A
        if replacement_budget.get(value, 0) > 0:
            replacement_budget[value] -= 1
            changed_before.append(Instruction("ADD", value))
            changed_after.append(Instruction("COPY", value))

    if not changed_before:
        return None

    return DetectionResult(
        refactoring_id="R08",
        refactoring_name="Replace ADD with COPY",
        instructions_before=tuple(changed_before),
        instructions_after=tuple(changed_after),
    )


@rule
def detect_add_env_variable(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R03 — Add ENV Variable.

    Directional mechanical rule over the ENV subset only: reports every ENV
    instruction in the after version that declares at least one variable
    NAME absent from the ENV declarations of the before version — the
    catalogue defines R03 as introducing a variable that centralises a
    value, so additions are the only direction. Changing the value of an
    already-declared name is a modification, not an addition, and removing
    an ENV is the reverse path: both are ignored by design.
    ``instructions_before`` is empty because an addition has no counterpart
    in version A.
    """
    names_a = set()
    for value in _values_of(instructions_a, "ENV"):
        names_a |= _env_names(value)

    added = [
        entry
        for entry in instructions_b
        if entry.instruction == "ENV" and _env_names(entry.value) - names_a
    ]
    if not added:
        return None

    return DetectionResult(
        refactoring_id="R03",
        refactoring_name="Add ENV Variable",
        instructions_before=(),
        instructions_after=tuple(added),
    )


@rule
def detect_add_arg_instruction(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R04 — Add ARG Instruction.

    Directional mechanical rule over the ARG subset only: reports every ARG
    instruction in the after version whose identifier (``NAME[=default]``)
    is absent from the ARG declarations of the before version — the
    catalogue defines R04 as introducing a build-time identifier, so
    additions are the only direction. Changing only the default value of an
    existing identifier is a modification, not an addition, and removing an
    ARG is the reverse path: both are ignored by design.
    ``instructions_before`` is empty because an addition has no counterpart
    in version A.
    """
    names_a = {_arg_name(value) for value in _values_of(instructions_a, "ARG")}

    added = [
        entry
        for entry in instructions_b
        if entry.instruction == "ARG" and _arg_name(entry.value) not in names_a
    ]
    if not added:
        return None

    return DetectionResult(
        refactoring_id="R04",
        refactoring_name="Add ARG Instruction",
        instructions_before=(),
        instructions_after=tuple(added),
    )


@rule
def detect_extract_stage(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R05 — Extract Stage.

    Directional rule over the stage structure, and the exact inverse of R06:
    work that used to run in the build that produces the final image is moved
    into a stage of its own, so the final image receives only what a
    ``COPY --from`` brings across and the build environment is discarded.

    A rising stage count is not evidence on its own, since a stage may simply
    be added to do new work. As with R06, the rule requires positive evidence
    that an existing build was split:

    1. the new stage is read from by a ``COPY --from`` in the after state;
    2. nothing read from that stage in the before state, so it is genuinely
       new rather than pre-existing;
    3. at least one of its instructions was already present in the before
       state, showing the work moved into the stage instead of being written
       there for the first time.

    Merging a stage back is the reverse path and belongs to R06.
    """
    stages_a = _stages(instructions_a)
    stages_b = _stages(instructions_b)

    # Directional: extraction increases the number of stages.
    if not stages_b or len(stages_b) <= len(stages_a):
        return None

    body_before = Counter(entry for stage in stages_a for entry in stage.instructions)
    references_before = {
        reference
        for reference in (_stage_reference_of(e) for e in instructions_a)
        if reference
    }

    for stage in stages_b:
        consumers = [
            entry for entry in instructions_b
            if _stage_reference_of(entry) == stage.identity
        ]
        if not consumers:
            continue  # nothing reads from it: not the extracted stage
        if stage.identity in references_before:
            continue  # already consumed before: the stage is not new
        moved = [entry for entry in stage.instructions if body_before[entry] > 0]
        if not moved:
            continue  # its work is new, not extracted from the previous build

        return DetectionResult(
            refactoring_id="R05",
            refactoring_name="Extract Stage",
            instructions_before=tuple(moved),
            instructions_after=tuple(consumers),
        )

    return None


@rule
def detect_inline_stage(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R06 — Inline Stage.

    Directional rule over the stage structure: a stage that provides no
    benefit is merged into the one that consumed it, so the redundant FROM
    and the ``COPY --from`` that read from it both disappear and the build
    collapses into fewer stages.

    A falling stage count is not evidence on its own, since a stage can also
    be plainly deleted. Following the same fusion-proof reasoning applied to
    R01, the rule looks for positive evidence that the stage was absorbed:

    1. the stage was read from by a ``COPY --from`` in the before state;
    2. no instruction reads from it any more in the after state;
    3. at least one instruction of that stage is now present in the
       surviving stages, showing its work moved rather than vanished.

    Splitting a stage in two is the reverse path and is never reported here.
    """
    stages_a = _stages(instructions_a)
    stages_b = _stages(instructions_b)

    # Directional: inlining reduces the number of stages.
    if not stages_a or len(stages_a) <= len(stages_b):
        return None

    body_after = Counter(entry for stage in stages_b for entry in stage.instructions)
    references_after = {
        reference
        for reference in (_stage_reference_of(e) for e in instructions_b)
        if reference
    }

    for stage in stages_a:
        consumers = [
            entry for entry in instructions_a
            if _stage_reference_of(entry) == stage.identity
        ]
        if not consumers:
            continue  # nothing consumed this stage: not the inlined one
        if stage.identity in references_after:
            continue  # still read from: the stage survives
        absorbed = [entry for entry in stage.instructions if body_after[entry] > 0]
        if not absorbed:
            continue  # its work vanished: a deletion, not an inlining

        return DetectionResult(
            refactoring_id="R06",
            refactoring_name="Inline Stage",
            instructions_before=tuple(consumers),
            instructions_after=tuple(absorbed),
        )

    return None


@rule
def detect_sort_instructions(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R07 — Sort Instructions.

    Directional rule over the instruction order: the same instructions appear
    in both states, rearranged so that stable, resource-intensive steps come
    before frequently modified ones, which is what preserves cache validity
    across rebuilds.

    Two conditions establish that the change is a pure rearrangement: the
    multiset of instructions is identical, so nothing was added, removed or
    edited, and the sequence differs. A commit that also edits an instruction
    is not a rearrangement and is not reported here.

    Direction is decided by counting cache inversions — volatile file
    transfers standing before dependency installations. The rearrangement
    qualifies only when that count falls, since moving a COPY ahead of a
    package installation invalidates the expensive layer on every source
    change and is technical debt rather than a refactoring.
    """
    if Counter(instructions_a) != Counter(instructions_b):
        return None  # something was added, removed or edited: not a reordering
    if instructions_a == instructions_b:
        return None  # same order: nothing was rearranged

    if _cache_inversions(instructions_b) >= _cache_inversions(instructions_a):
        return None  # the rearrangement does not improve cache ordering

    moved_before = tuple(
        entry for index, entry in enumerate(instructions_a)
        if instructions_b[index] != entry
    )
    moved_after = tuple(
        entry for index, entry in enumerate(instructions_b)
        if instructions_a[index] != entry
    )

    return DetectionResult(
        refactoring_id="R07",
        refactoring_name="Sort Instructions",
        instructions_before=moved_before,
        instructions_after=moved_after,
    )


@rule
def detect_extract_run_instructions(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R09 — Extract RUN Instructions.

    Directional rule over the RUN and COPY/ADD subsets: a complex inline shell
    sequence is taken out of a RUN into an external script, which the
    Dockerfile then copies in and executes, leaving a single call in place of
    the chained commands.

    The script itself is a file outside the Dockerfile, and the pipeline never
    sees it — the VCS Connector delivers one Dockerfile at two commits. As with
    Move Stage (R11), the refactoring is still decidable from the Dockerfile
    alone, because moving work into a script leaves three facts in the file:

    1. a COPY or ADD that did not exist before brings a shell script into the
       image, so a new external artefact arrived;
    2. a RUN executes that script, which is what ties the new artefact to the
       build rather than leaving it as an unused file;
    3. the total number of shell command segments across the RUN instructions
       falls, showing the commands left the Dockerfile instead of being written
       into the script for the first time.

    The third condition is what distinguishes the refactoring from simply
    adding new functionality through a script: without shell work leaving the
    file nothing was extracted. Inlining a script's contents back into a RUN is
    the reverse path — the script COPY disappears rather than appears — and is
    never reported.
    """
    # Scripts the image already received, by file name: a script whose
    # destination merely changed is not a newly extracted one.
    scripts_before = {
        path.rsplit("/", 1)[-1]
        for entry in instructions_a
        if entry.instruction in _FILE_TRANSFER_INSTRUCTIONS
        for path in _script_destinations(entry)
    }
    runs_a = _values_of(instructions_a, "RUN")
    runs_b = _values_of(instructions_b, "RUN")

    # Directional: extraction removes shell work from the Dockerfile.
    segments_a = sum(len(_shell_segments(value)) for value in runs_a)
    segments_b = sum(len(_shell_segments(value)) for value in runs_b)
    if segments_b >= segments_a:
        return None

    surviving_runs = set(runs_b)
    extracted = [
        Instruction("RUN", value) for value in runs_a if value not in surviving_runs
    ]
    if not extracted:
        return None  # nothing changed in the RUN bodies: no work to extract

    for entry in instructions_b:
        if entry.instruction not in _FILE_TRANSFER_INSTRUCTIONS:
            continue
        for path in _script_destinations(entry):
            if path.rsplit("/", 1)[-1] in scripts_before:
                continue  # the script was already in the image: nothing arrived now
            callers = [
                Instruction("RUN", value)
                for value in runs_b
                if _invokes_script(value, path)
            ]
            if not callers:
                continue  # the script is copied in but never executed

            return DetectionResult(
                refactoring_id="R09",
                refactoring_name="Extract RUN Instructions",
                instructions_before=tuple(extracted),
                instructions_after=(entry,) + tuple(callers),
            )

    return None


@rule
def detect_update_base_image(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R10 — Update Base Image.

    Granular rule over the FROM subset, aligned by stage position: reports
    every FROM whose base-image ENTITY was substituted — the repository
    name differs while platform flags and stage alias are preserved. The
    tag and digest are free to change as part of the new image reference.
    This is the exact complement of R02's entity-preservation condition, so
    the two rules are mutually exclusive per FROM by construction.

    Direction note (author's decision, Option A, 2026-07-06): the catalogue
    direction — "towards a lighter and more secure alternative" — is
    empirical by nature (ΔSize, ΔCVEs) and cannot be decided by static text
    comparison. The rule therefore detects the structural operation for any
    entity substitution, and the direction is verified downstream by the
    Performance Analyzer and Data Extractor measurements, with the RF6
    trade-off flag exposing degradations. This is a documented exception to
    the static directional law. When the number of FROMs differs, stage
    alignment is ambiguous (Extract/Inline Stage territory) and the rule
    stays silent.
    """
    froms_a = _from_instructions(instructions_a)
    froms_b = _from_instructions(instructions_b)
    if not froms_a or len(froms_a) != len(froms_b):
        return None

    changed_before = []
    changed_after = []
    for before, after in zip(froms_a, froms_b):
        if before == after:
            continue
        parts_before = _parse_from_value(before.value)
        parts_after = _parse_from_value(after.value)
        entity_substitution = (
            parts_before.name != parts_after.name
            and parts_before.flags == parts_after.flags
            and parts_before.alias == parts_after.alias
        )
        if entity_substitution:
            changed_before.append(before)
            changed_after.append(after)

    if not changed_before:
        return None

    return DetectionResult(
        refactoring_id="R10",
        refactoring_name="Update Base Image",
        instructions_before=tuple(changed_before),
        instructions_after=tuple(changed_after),
    )


@rule
def detect_move_stage(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R11 — Move Stage.

    Directional rule over the stage structure: a stage is taken out of the
    Dockerfile into a standalone one of its own, built separately, and the
    main file keeps only a reference to the image that build produces.

    The extracted Dockerfile is a second file the pipeline never sees, since
    the VCS Connector delivers one Dockerfile at two commits. The refactoring
    is nonetheless visible in the main file alone, because it leaves a precise
    signature: the stage stays in place and stays consumed, but its body moves
    out and its FROM now names an externally built image. Three facts
    establish it:

    1. the stage had a body in the before state and has none in the after
       state, so its work left the file;
    2. its FROM reference changed, meaning the emptied stage now names the
       image produced elsewhere rather than the original base — an emptied
       stage still on the same base would be a deletion;
    3. something still reads from it, so the build continues to consume what
       the stage delivers.

    The stage count is unchanged by this refactoring, which is what separates
    it from Extract Stage (R05) and Inline Stage (R06).
    """
    stages_a = _stages(instructions_a)
    stages_b = _stages(instructions_b)
    if not stages_a or not stages_b:
        return None

    froms_b = [entry for entry in instructions_b if entry.instruction == "FROM"]
    stages_b_by_identity = {stage.identity: stage for stage in stages_b}
    references_after = {
        reference
        for reference in (_stage_reference_of(e) for e in instructions_b)
        if reference
    }

    for stage in stages_a:
        if not stage.instructions:
            continue  # no body to move out
        moved = stages_b_by_identity.get(stage.identity)
        if moved is None or moved.instructions:
            continue  # the stage is gone, or still holds its work
        if moved.reference == stage.reference:
            continue  # emptied but on the same base: a deletion, not a move
        if stage.identity not in references_after:
            continue  # nothing consumes it any more

        return DetectionResult(
            refactoring_id="R11",
            refactoring_name="Move Stage",
            instructions_before=stage.instructions,
            instructions_after=(froms_b[moved.index],),
        )

    return None


@rule
def detect_remove_run_mv(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R12 — Remove RUN Instruction (mv command).

    Granular, directional rule over the RUN and COPY/ADD subsets: a RUN whose
    sole purpose is to execute a move is eliminated, and the destination path
    it produced is set directly in the preceding COPY or ADD instruction, so
    the layer the move created disappears.

    A RUN vanishing is not enough on its own, since that alone is a deletion.
    The relocation must be shown to have moved into the transfer instruction,
    which requires three facts to hold together:

    1. the RUN does nothing but move files (``mkdir`` is tolerated, as it only
       prepares the directory that COPY creates by itself);
    2. in the before state a COPY or ADD landed on the path the move read
       from, typically a temporary location;
    3. in the after state a COPY or ADD carrying the same sources lands
       directly on the path the move wrote to.

    Adding a ``RUN mv`` is the reverse path and is never reported.
    """
    surviving_runs = set(_values_of(instructions_b, "RUN"))
    transfers_a = [e for e in instructions_a if e.instruction in _FILE_TRANSFER_INSTRUCTIONS]
    transfers_b = [e for e in instructions_b if e.instruction in _FILE_TRANSFER_INSTRUCTIONS]

    removed_runs, direct_transfers = [], []
    for entry in instructions_a:
        if entry.instruction != "RUN" or entry.value in surviving_runs:
            continue
        relocations = _move_relocations(entry.value)
        if not relocations:
            continue

        for source, destination in relocations:
            # the transfer that used to land on the path the move read from
            origin = next(
                (e for e in transfers_a
                 if (ops := _transfer_operands(e.value)) and ops[1] == source),
                None,
            )
            if origin is None:
                continue
            origin_sources = _transfer_operands(origin.value)[0]
            # the same sources now landing straight on the move's destination
            landed = next(
                (e for e in transfers_b
                 if (ops := _transfer_operands(e.value))
                 and ops[1] == destination
                 and ops[0] == origin_sources),
                None,
            )
            if landed is None:
                continue
            removed_runs.append(entry)
            if landed not in direct_transfers:
                direct_transfers.append(landed)
            break  # one confirmed relocation is enough for this RUN

    if not removed_runs:
        return None

    return DetectionResult(
        refactoring_id="R12",
        refactoring_name="Remove RUN Instruction (mv command)",
        instructions_before=tuple(removed_runs),
        instructions_after=tuple(direct_transfers),
    )


@rule
def detect_update_run_instruction(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R13 — Update RUN Instruction.

    Granular rule over the RUN subset, aligned by position: a RUN is reported
    when its text changed while the commands and arguments it carries stayed
    exactly the same. That is what this refactoring does — split a long
    instruction across lines with backslashes, and sort its arguments
    alphanumerically — so the package set and the versions are identical on
    both sides and only the physical layout or the order differs.

    The comparison is a multiset of whitespace-separated tokens. It matches
    both components of the refactoring: reordering keeps the same tokens in a
    different sequence, and line splitting keeps the same tokens with
    different spacing, since continuations resolve into the argument string.
    Adding, removing or re-versioning a package changes the token multiset, so
    such a change is a content edit and is never reported here.

    When the number of RUN instructions differs the change belongs to
    consolidation or removal (R01, R12) and the rule stays silent.
    """
    runs_a = _values_of(instructions_a, "RUN")
    runs_b = _values_of(instructions_b, "RUN")
    if not runs_a or len(runs_a) != len(runs_b):
        return None

    changed_before, changed_after = [], []
    for before, after in zip(runs_a, runs_b):
        if before == after:
            continue
        if Counter(before.split()) == Counter(after.split()):
            changed_before.append(Instruction("RUN", before))
            changed_after.append(Instruction("RUN", after))

    if not changed_before:
        return None

    return DetectionResult(
        refactoring_id="R13",
        refactoring_name="Update RUN Instruction",
        instructions_before=tuple(changed_before),
        instructions_after=tuple(changed_after),
    )


@rule
def detect_rename_image(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R14 — Rename Image.

    Granular rule over the FROM subset, aligned by stage position. A FROM
    qualifies only when the image reference is untouched — identical
    repository name, tag, digest, and platform flags (otherwise the change
    belongs to R02/R10) — and the stage alias mutates according to the
    validation logic fixed by the author (2026-07-06):

    - Accepted, alias appears: no alias before, alias after (e.g.
      ``FROM golang:1.22`` → ``FROM golang:1.22 AS build``), eliminating
      the technical debt of numeric stage references such as ``--from=0``.
    - Accepted, alias changes: different non-empty aliases (e.g.
      ``AS build`` → ``AS builder``), the direct syntactic equivalent of
      DRMiner's Rename Image behaviour.
    - Excluded, alias disappears: alias before, none after — the reverse
      path, reintroducing numeric-reference debt; ignored by design.

    Scope is the FROM instruction only: consequential updates to
    ``--from=`` references elsewhere are tolerated noise, not part of the
    detection. When the number of FROMs differs, stage alignment is
    ambiguous (Extract/Inline Stage territory) and the rule stays silent.
    """
    froms_a = _from_instructions(instructions_a)
    froms_b = _from_instructions(instructions_b)
    if not froms_a or len(froms_a) != len(froms_b):
        return None

    changed_before = []
    changed_after = []
    for before, after in zip(froms_a, froms_b):
        if before == after:
            continue
        parts_before = _parse_from_value(before.value)
        parts_after = _parse_from_value(after.value)
        image_untouched = (
            parts_before.name == parts_after.name
            and parts_before.tag == parts_after.tag
            and parts_before.digest == parts_after.digest
            and parts_before.flags == parts_after.flags
        )
        alias_appears = not parts_before.alias and parts_after.alias
        alias_changes = (
            parts_before.alias
            and parts_after.alias
            and parts_before.alias != parts_after.alias
        )
        if image_untouched and (alias_appears or alias_changes):
            changed_before.append(before)
            changed_after.append(after)

    if not changed_before:
        return None

    return DetectionResult(
        refactoring_id="R14",
        refactoring_name="Rename Image",
        instructions_before=tuple(changed_before),
        instructions_after=tuple(changed_after),
    )
