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
from dataclasses import dataclass, field
from typing import Callable, NamedTuple, Optional

from dockerfile_parse import DockerfileParser


class DockerfileParseError(Exception):
    """Dockerfile content could not be parsed into logical instructions.

    RNF4: parsing failures surface as this specific exception instead of the
    raw error of the underlying library, so the pipeline can distinguish
    malformed content from a build or daemon failure.
    """


# How an instruction was written in the source. R13 refactors presentation
# rather than content, so the typography is evidence and has to survive
# parsing, which is where continuations and heredocs are otherwise dissolved.
LAYOUT_SINGLE = "single"  # written on one physical line
LAYOUT_MULTI = "multi"  # split across backslash continuations
LAYOUT_HEREDOC = "heredoc"  # written as a heredoc block


@dataclass(frozen=True)
class Instruction:
    """One logical Dockerfile instruction (multi-line RUNs already joined).

    ``layout`` is excluded from equality and hashing on purpose: two
    instructions carrying the same command are the same instruction whatever
    their typography, and a rule that rebuilds one to report it must not
    compare unequal to the parsed original merely for lacking a layout it
    never observed. Only R13, which is about typography, reads the field.
    """

    instruction: str  # e.g. "FROM", "RUN" (upper-case, per dockerfile-parse)
    value: str  # argument string with continuations resolved
    layout: str = field(default=LAYOUT_SINGLE, compare=False)


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


# A heredoc opener: ``<<EOS``, ``<<-EOS``, ``<<"EOS"`` or ``<<'EOS'``.
_HEREDOC_START = re.compile(r'''<<-?\s*['"]?([A-Za-z_][A-Za-z0-9_]*)['"]?''')


def _collapse_heredocs(content: str) -> str:
    """Fold heredoc blocks into the instruction line that opens them.

    dockerfile-parse 2.0.1 predates the heredoc syntax: given

        RUN <<EOS
        apt-get update
        apt-get clean
        EOS

    it reports ``RUN <<EOS`` and then invents an instruction per body line
    (``APT-GET: update``), so the commands never reach the rules. Folding the
    block into one logical line before parsing restores them without changing
    the parser, which Experiment 5 validated and the design chapter names.

    The body is joined with ``&&`` because that is what the heredoc form means:
    a heredoc with ``set -e`` fails on the first error exactly as a chain does,
    so the two forms carry the same commands with the same semantics. The
    collapsed line is what a rule reports as the instruction involved, so a
    detection on a heredoc names its commands rather than the opener alone.
    """
    lines = content.split(chr(10))
    output = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = _HEREDOC_START.search(line)
        if not match:
            output.append(line)
            index += 1
            continue

        terminator = match.group(1)
        body = []
        cursor = index + 1
        while cursor < len(lines) and lines[cursor].strip() != terminator:
            if lines[cursor].strip():
                body.append(lines[cursor].strip())
            cursor += 1

        if cursor >= len(lines):
            # No terminator: not a heredoc after all, leave the text alone.
            output.append(line)
            index += 1
            continue

        head = line[: match.start()].rstrip()
        tail = line[match.end():].strip()
        collapsed = " && ".join(body)
        output.append(" ".join(part for part in (head, tail, collapsed) if part))
        index = cursor + 1
    return chr(10).join(output)


# A backslash closing a physical line: the continuation marker.
_CONTINUATION = re.compile(r"\\[ \t]*$")


def _layout_classes(content: str) -> list:
    """Presentation class of each logical instruction, in file order.

    Read from the source as committed, because the information does not
    survive parsing: dockerfile-parse resolves continuations into the
    argument string and ``_collapse_heredocs`` folds heredoc bodies away,
    so by the time a rule sees an instruction its typography is gone. R13
    detects a change of typography, so the classes are collected here and
    travel on the Instruction.

    The scan segments instructions the way the Dockerfile format does: a
    heredoc runs to its terminator, a line closing with a backslash
    continues into the next, anything else is one line. Blanks and comments
    are skipped, which is the subset ``parse_instructions`` returns, so the
    two align one-to-one; when they do not, the caller discards the result
    rather than risk pairing a class with the wrong instruction.
    """
    lines = content.split(chr(10))
    classes = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue

        opener = _HEREDOC_START.search(lines[index])
        if opener:
            terminator = opener.group(1)
            index += 1
            while index < len(lines) and lines[index].strip() != terminator:
                index += 1
            index += 1  # consume the terminator
            classes.append(LAYOUT_HEREDOC)
            continue

        spans = False
        while index < len(lines) and _CONTINUATION.search(lines[index].rstrip()):
            spans = True
            index += 1
        index += 1
        classes.append(LAYOUT_MULTI if spans else LAYOUT_SINGLE)
    return classes


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
    normalised = dockerfile_content.replace("\r\n", "\n")
    try:
        parser = DockerfileParser(fileobj=io.BytesIO())
        parser.content = _collapse_heredocs(normalised)
        structure = parser.structure
    except Exception as exc:  # noqa: BLE001 — any parser failure is malformed content
        raise DockerfileParseError(
            f"Dockerfile content could not be parsed into logical "
            f"instructions: {exc}"
        ) from exc

    entries = [entry for entry in structure if entry["instruction"] != "COMMENT"]
    layouts = _layout_classes(normalised)
    if len(layouts) != len(entries):
        # The scan and the parser disagree on where instructions begin, so
        # no class can be trusted to belong to its instruction. Reporting
        # every instruction as single-line costs R13 a detection; guessing
        # would cost it a wrong one.
        layouts = [LAYOUT_SINGLE] * len(entries)

    return [
        Instruction(entry["instruction"], entry["value"], layout)
        for entry, layout in zip(entries, layouts)
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


# A RUN may be written as a shell string, as an exec-form JSON array, or as a
# heredoc block. All three carry commands; only the packaging differs.
_EXEC_FORM = re.compile(r"^\s*\[\s*(.+)\s*\]\s*$", re.S)
_HEREDOC_OPENER = re.compile(r'''<<-?\s*['"]?([A-Za-z_][A-Za-z0-9_]*)['"]?''')
# Shell scaffolding that expresses fail-fast rather than a command of its own:
# `&&` provides it in the chained form, `set -e` in the heredoc form.
# A shell or build variable reference: ``$NAME`` or ``${NAME}``.
_VARIABLE_REFERENCE = re.compile(r"\$\{?[A-Za-z_]")
_SHELL_DIRECTIVE = re.compile(r"^set\s+[-+][a-zA-Z]+(\s+[-+][a-zA-Z]+)*$")


def _shell_body(value: str) -> str:
    """The commands a RUN carries, freed from the form they are written in.

    An exec-form ``RUN ["/bin/sh", "-c", "..."]`` hides its commands inside a
    JSON array, and a heredoc hides them after the opener. Both are unwrapped
    so the segment split below sees commands rather than punctuation.
    """
    text = value.strip()

    match = _EXEC_FORM.match(text)
    if match:
        try:
            import json as _json
            elements = _json.loads(text)
        except Exception:  # noqa: BLE001 — not valid JSON: treat as a shell string
            return text
        if isinstance(elements, list) and elements:
            # ["/bin/sh", "-c", "<commands>"] carries its commands in the last
            # element; a bare ["prog", "arg"] is a single command.
            if len(elements) >= 3 and str(elements[0]).endswith("sh"):
                return str(elements[-1])
            return " ".join(str(element) for element in elements)
        return text

    opener = _HEREDOC_OPENER.search(text)
    if opener:
        terminator = opener.group(1)
        lines = text.splitlines()
        body = []
        started = False
        for line in lines:
            if not started:
                if opener.group(0) in line:
                    started = True
                continue
            if line.strip() == terminator:
                break
            body.append(line)
        if body:
            return chr(10).join(body)
    return text


def _shell_segments(value: str) -> list:
    """Command segments of a RUN body, whitespace-normalised.

    Consolidating RUN instructions chains what were separate commands with
    ``&&`` (or ``;`` / ``||``), so splitting on those operators recovers the
    commands the separate instructions used to hold. A heredoc separates the
    same commands by newline instead, so newlines split too. Whitespace is
    normalised because a multi-line RUN joined by backslash continuations keeps
    the indentation of the physical lines inside its argument string.
    """
    body = _shell_body(value)
    parts = []
    for line in body.splitlines():
        parts.extend(_SHELL_SEPARATORS.split(line))
    return [" ".join(part.split()) for part in parts if part.split()]


def _run_commands(value: str) -> Counter:
    """The words a RUN carries, as a multiset, ignoring how they are packaged.

    Two RUN bodies match when they hold the same words, whatever their layout:
    chained with ``&&``, split across backslash continuations, wrapped in an
    exec-form array or written as a heredoc. Counting words rather than whole
    commands is what also makes argument reordering match, since sorting a
    package list alphabetically changes the order of the words and nothing
    else.

    Shell directives such as ``set -eux`` are dropped: they express fail-fast,
    which the chained form expresses with ``&&`` instead, so their presence or
    absence marks a change of notation and not a change of commands.
    """
    return Counter(
        word
        for segment in _shell_segments(value)
        if not _SHELL_DIRECTIVE.match(segment)
        for word in segment.split()
    )


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


def _names_a_stage(reference: str, stages: list) -> bool:
    """True when a ``--from=`` reference names a stage of this Dockerfile.

    A ``--from`` may name a stage or an image. Telling them apart is what
    separates Inline Stage from Move Stage: work absorbed by another stage of
    the same file stays inside it, whereas work that left the file comes back
    through a reference to a published image.
    """
    identities = {stage.identity for stage in stages}
    return reference.lower() in identities


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
# Commands that only serve the relocation and disappear along with it, so a
# RUN carrying them is still an instruction whose sole purpose is the move:
#   mkdir  prepares the directory the move lands in; COPY creates it by itself
#   chmod  sets the mode the surviving transfer expresses with --chmod
# A `set -...` line is shell scaffolding and is skipped before this check.
_MOVE_COMPANION_COMMANDS = {"mkdir", "chmod"}


def _transfer_operands(value: str):
    """(sources, destination) of a COPY or ADD, or None when malformed.

    Flags such as ``--from`` or ``--chown`` are skipped; the destination is
    the last operand, as the Dockerfile syntax defines.
    """
    tokens = [token for token in value.split() if not token.startswith("--")]
    if len(tokens) < 2:
        return None
    return tuple(tokens[:-1]), tokens[-1]


def _transfer_key(value: str):
    """Flags, sources and destination of a COPY or ADD, normalised.

    What identifies a transfer is what it moves and where to, not how the line
    is laid out. Flags are ordered so their sequence cannot matter, and the
    operands come from ``_transfer_operands``, which already splits on
    whitespace — so a line broken across backslash continuations, whose value
    keeps the indentation of the physical lines, reduces to the same key as the
    single-line form.

    Returns None for a malformed transfer, which then matches nothing.
    """
    operands = _transfer_operands(value)
    if operands is None:
        return None
    flags = tuple(sorted(token for token in value.split() if token.startswith("--")))
    sources, destination = operands
    return flags, tuple(sources), destination


def _path(value: str) -> str:
    """A filesystem path reduced to what it names.

    ``/tmp/assets`` and ``/tmp/assets/`` are the same directory to Docker,
    and a commit is free to write either. Comparing them as text makes two
    references to one location look like two locations.
    """
    return value.rstrip("/") or "/"

def _instruction_key(entry) -> tuple:
    """An instruction reduced to what identifies it, ignoring its layout.

    Used where a rule has to recognise the same instruction in both states
    without demanding the same text. A transfer is keyed on its flags, sources
    and destination, with any trailing separator dropped so ``fixtures`` and
    ``fixtures/`` name the same path; every other instruction is keyed on its
    keyword and its whitespace-normalised argument string, which is what makes
    a line broken across continuations equal to the single-line form.
    """
    if entry.instruction in _FILE_TRANSFER_INSTRUCTIONS:
        key = _transfer_key(entry.value)
        if key is not None:
            flags, sources, destination = key
            return (
                entry.instruction,
                flags,
                tuple(source.rstrip("/") for source in sources),
                destination.rstrip("/"),
            )
    return (entry.instruction, " ".join(entry.value.split()))


def _move_relocations(value: str):
    """(source, destination) of every mv in a RUN body, or None.

    Returns None when the RUN does anything beyond relocating files, so that
    only instructions whose sole purpose is the move are considered.
    """
    relocations = []
    removals = []
    for segment in _shell_segments(value):
        tokens = segment.split()
        if not tokens:
            continue
        if _SHELL_DIRECTIVE.match(segment):
            continue  # `set -eux` expresses fail-fast, not work
        command = tokens[0]
        if command == "mv":
            operands = [token for token in tokens[1:] if not token.startswith("-")]
            if len(operands) != 2:
                return None  # multi-source move: not a single relocation
            relocations.append((operands[0], operands[1]))
        elif command == "rm":
            # Deferred: a removal is tolerable only when it clears the staging
            # location the move read from, which the relocations below decide.
            removals.extend(
                token for token in tokens[1:] if not token.startswith("-")
            )
        elif command not in _MOVE_COMPANION_COMMANDS:
            return None  # the RUN does more than move files
    if not relocations:
        return None

    # A `rm` is part of the relocation only when it clears a staging path the
    # move emptied. Removing anything else is work of its own, and a RUN that
    # does work beyond relocating is not what this refactoring eliminates.
    staged = set()
    for source, _destination in relocations:
        staged.add(source.rstrip("/"))
        parent = source.rstrip("/").rsplit("/", 1)[0]
        if parent:
            staged.add(parent)
    for removed in removals:
        if removed.rstrip("/") not in staged:
            return None

    return relocations


def _absorption_key(entry) -> tuple:
    """What identifies an instruction that survived being moved between stages.

    Collapsing a stage into the one that consumed it removes the intermediate
    location the work used to pass through, so the instructions arrive with
    their operands adjusted: a file staged at ``/tmp/x`` is written straight to
    ``/etc/x``. Matching on the full text would miss every such case, so the
    key keeps what the instruction *does* and drops what the collapse is
    expected to change.

    A transfer is keyed on its sources — the destination is precisely what
    moves. A RUN is keyed on the leading command of each of its segments, so
    ``sed -i "..." /tmp/x`` still matches ``sed -i "..." /etc/x``. Anything
    else is keyed on its keyword and normalised text, as before.
    """
    if entry.instruction in _FILE_TRANSFER_INSTRUCTIONS:
        operands = _transfer_operands(entry.value)
        if operands is not None:
            sources, _destination = operands
            return (entry.instruction, tuple(s.rstrip("/") for s in sources))
    if entry.instruction == "RUN":
        commands = tuple(
            segment.split()[0]
            for segment in _shell_segments(entry.value)
            if segment.split() and not _SHELL_DIRECTIVE.match(segment)
        )
        return (entry.instruction, commands)
    return (entry.instruction, " ".join(entry.value.split()))


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


_SCRIPT_INVOCATION = re.compile(r"([\w./~$-]+\.(?:sh|bash))")


def _invoked_scripts(value: str) -> set:
    """Paths of the shell scripts a RUN body executes.

    Built on the same positional test ``_invokes_script`` applies: a script
    counts as executed only where a command stands, either as a segment's own
    command or as the file handed to an interpreter. A path merely passed to
    another command prepares the script without running it.
    """
    found = set()
    for candidate in _SCRIPT_INVOCATION.findall(value):
        if _invokes_script(value, candidate):
            found.add(candidate)
    return found


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


# --- Build-argument resolution and image reference canonicalisation -----------

_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _global_args(instructions: list) -> dict:
    """Default values of the ARGs a FROM instruction may read.

    Docker resolves variables in a FROM against the ARGs declared before the
    first FROM; an ARG inside a stage is not visible there. Only those are
    collected, so the expansion mirrors what the daemon would do.
    """
    values = {}
    for entry in instructions:
        if entry.instruction == "FROM":
            break
        if entry.instruction == "ARG" and "=" in entry.value:
            name, _, default = entry.value.partition("=")
            values[name.strip()] = default.strip()
    return values


def _expand_variables(value: str, variables: dict) -> str:
    """Substitute ``${NAME}``, ``${NAME:-fallback}`` and ``$NAME`` in a value.

    A name with no known value is left as written: an unresolvable reference is
    not evidence of anything, and substituting an empty string would invent a
    difference between two states that both fail to resolve it.
    """
    def replace(match):
        braced, fallback, bare = match.group(1), match.group(2), match.group(3)
        name = braced or bare
        if name in variables:
            return variables[name]
        if fallback is not None:
            return fallback
        return match.group(0)

    return _VARIABLE.sub(replace, value)


# Prefixes Docker itself adds when it resolves a bare image name. A reference
# that only gains or loses them still names the same image.
_DEFAULT_REGISTRIES = ("index.docker.io/", "docker.io/")
_DEFAULT_NAMESPACE = "library/"


def _canonical_image_name(name: str) -> str:
    """The image name with the implicit registry and namespace removed.

    ``docker.io/library/python`` and ``python`` are the same image, so a change
    between them is a notation change and not a base-image substitution. Only
    the registry Docker assumes by default is stripped: a move to a genuinely
    different registry keeps its host and stays visible as a difference.
    """
    canonical = name
    for registry in _DEFAULT_REGISTRIES:
        if canonical.startswith(registry):
            canonical = canonical[len(registry) :]
            if canonical.startswith(_DEFAULT_NAMESPACE):
                canonical = canonical[len(_DEFAULT_NAMESPACE) :]
            break
    return canonical


def _resolved_from_parts(instructions: list) -> list:
    """The FROM instructions with their variables expanded and names canonical.

    Returns one ``(instruction, parts)`` pair per FROM, in stage order, so the
    FROM rules compare what Docker would actually build rather than the text as
    written.
    """
    variables = _global_args(instructions)
    resolved = []
    for entry in _from_instructions(instructions):
        parts = _parse_from_value(_expand_variables(entry.value, variables))
        resolved.append((entry, parts._replace(name=_canonical_image_name(parts.name))))
    return resolved


def _stage_identities_before(resolved: list, position: int) -> set:
    """Names an earlier stage can be referenced by, at a given FROM position.

    A FROM may build on a previous stage instead of an image
    (``FROM builder AS vet``). Such a reference is not an image at all, so the
    rules that compare base images must leave it alone.
    """
    identities = set()
    for index, (_entry, parts) in enumerate(resolved[:position]):
        identities.add(str(index))
        if parts.alias:
            identities.add(parts.alias.lower())
    return identities


def _pair_from_instructions(resolved_a: list, resolved_b: list) -> list:
    """Match the FROM instructions of two states to each other.

    Positional alignment breaks as soon as a commit also adds or removes a
    stage: the FROMs after the change sit at different indices, and a rule that
    demands equal counts falls silent on every mixed commit. Matching by
    identity instead lets the FROM rules keep working on exactly the stages
    that survived.

    A FROM matches its counterpart when they share an alias, or failing that
    when they name the same canonical image — the second is what pairs a stage
    whose alias is precisely what changed. Candidates are consumed greedily and
    in order, so each FROM of the earlier state answers for at most one of the
    later state; a FROM with no counterpart is skipped rather than silencing
    the rule.

    Returns ``(entry_before, parts_before, entry_after, parts_after, position)``
    per matched pair, where the position is the index in the later state, used
    to tell a stage reference from an image.
    """
    available = list(enumerate(resolved_a))
    matched = []
    # The final stage is the one that produces the image in both states, so it
    # is paired before any other. Left to its turn it would find its
    # counterpart already claimed by a name match from an earlier stage, and a
    # base-image substitution on the stage that actually ships would be lost.
    order = [len(resolved_b) - 1] + list(range(len(resolved_b) - 1))
    for position in order:
        after, parts_after = resolved_b[position]
        chosen = None
        for candidate in (
            # Both the alias and the image agreeing is the strongest evidence
            # that two FROMs are the same stage, and trying it first stops a
            # bare name match from claiming a FROM that a differently-named
            # stage at the same position needs.
            lambda pair: (pair[1][1].alias == parts_after.alias
                          and pair[1][1].name == parts_after.name),
            lambda pair: pair[1][1].alias and pair[1][1].alias == parts_after.alias,
            lambda pair: pair[1][1].name == parts_after.name,
            # Neither the alias nor the name survives when the base image is
            # substituted outright, which is exactly what R10 detects, so
            # position is the last thing left to match on — counted from the
            # end, because the final stage is the one that produces the image
            # in both states. Counting from the start would pair the old base
            # with whatever new stage was prepended, reporting a substitution
            # that never happened.
            lambda pair: (len(resolved_a) - 1 - pair[0]
                          == len(resolved_b) - 1 - position),
        ):
            found = next((pair for pair in available if candidate(pair)), None)
            if found is not None:
                chosen = found
                break
        if chosen is None:
            continue
        available.remove(chosen)
        _index, (before, parts_before) = chosen
        matched.append((position, before, parts_before, after, parts_after))
    # Restored to the order the stages appear in, so a rule reports its
    # findings in the order a reader meets them in the file.
    matched.sort(key=lambda item: item[0])
    return [(b, pb, a, pa, pos) for pos, b, pb, a, pa in matched]


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

    # A surviving RUN is a merge when no single previous RUN could account for
    # everything it carries, and what it carries traces back to two or more of
    # them. The first condition is what stops a segment that merely appears in
    # several RUNs — `apt-get update` is in almost every Dockerfile twice —
    # from making an untouched instruction look like a consolidation.
    before_segments = [set(_shell_segments(value)) for value in runs_a]
    merged_after = []
    merged_origins = set()
    for value in runs_b:
        segments = set(_shell_segments(value))
        origins = set()
        for segment in segments:
            origins |= segment_origin.get(segment, set())
        explained_by_one = any(
            segments <= candidate for candidate in before_segments
        )
        if len(origins) >= 2 and not explained_by_one:
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
    resolved_a = _resolved_from_parts(instructions_a)
    resolved_b = _resolved_from_parts(instructions_b)
    if not resolved_a or not resolved_b:
        return None

    changed_before = []
    changed_after = []
    for before, parts_before, after, parts_after, position in _pair_from_instructions(
        resolved_a, resolved_b
    ):
        # A FROM may build on an earlier stage rather than an image. That is a
        # stage reference, not a base image, and no image rule applies to it.
        stages_before = _stage_identities_before(resolved_a, position)
        stages_after = _stage_identities_before(resolved_b, position)
        if (parts_before.name.lower() in stages_before
                or parts_after.name.lower() in stages_after):
            continue

        # The image entity, and only the image entity: whether the stage was
        # also renamed in the same commit is R14's finding, not this rule's.
        # Each FROM rule judges one dimension — this one the tag, R10 the
        # entity, R14 the alias — so a commit that changes two of them at once
        # reports both rather than neither.
        entity_preserved = (
            parts_before.name == parts_after.name
            and parts_before.digest == parts_after.digest
            and parts_before.flags == parts_after.flags
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

    # Keyed on what each transfer moves and where to, rather than on its
    # argument string. The refactoring swaps the keyword and may reformat the
    # line in the same edit — breaking it across continuations, for instance —
    # and a byte comparison would miss every such case.
    def keyed(values):
        counted = Counter()
        for value in values:
            key = _transfer_key(value)
            if key is not None:
                counted[key] += 1
        return counted

    adds_a_keys = [(_transfer_key(v), v) for v in adds_a]
    adds_b_counts = keyed(_values_of(instructions_b, "ADD"))
    copies_a_counts = keyed(_values_of(instructions_a, "COPY"))
    copies_b_values = _values_of(instructions_b, "COPY")
    copies_b_counts = keyed(copies_b_values)

    # For each transfer, the number of replacements is bounded both by the ADDs
    # that disappeared and by the COPYs that appeared.
    replacement_budget = {}
    for key, value in adds_a_keys:
        if key is None or key in replacement_budget:
            continue
        if _uses_add_only_capability(value):
            continue
        removed_adds = sum(1 for k, _ in adds_a_keys if k == key) - adds_b_counts[key]
        gained_copies = copies_b_counts[key] - copies_a_counts[key]
        replacement_budget[key] = min(removed_adds, gained_copies)

    # The surviving COPY is reported as written, so the report shows the text
    # the commit actually produced rather than a reconstruction of it.
    copy_by_key = {}
    for value in copies_b_values:
        copy_by_key.setdefault(_transfer_key(value), value)

    changed_before = []
    changed_after = []
    for key, value in adds_a_keys:  # original order of the ADDs in version A
        if replacement_budget.get(key, 0) > 0:
            replacement_budget[key] -= 1
            changed_before.append(Instruction("ADD", value))
            changed_after.append(Instruction("COPY", copy_by_key.get(key, value)))

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

    # Matched by what each instruction does rather than by its exact text: the
    # collapse removes the intermediate location the work passed through, so
    # the absorbed instructions arrive with their operands adjusted.
    body_after = Counter(
        _absorption_key(entry) for stage in stages_b for entry in stage.instructions
    )
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
        absorbed = [
            entry for entry in stage.instructions
            if body_after[_absorption_key(entry)] > 0
        ]
        if not absorbed:
            continue  # its work vanished: a deletion, not an inlining

        return DetectionResult(
            refactoring_id="R06",
            refactoring_name="Inline Stage",
            instructions_before=tuple(consumers),
            instructions_after=tuple(absorbed),
        )

    return None


def _sort_identity(entry: Instruction) -> tuple:
    """An instruction reduced to what identifies it across a rearrangement.

    A file transfer is identified by what it brings into the image and not
    by where that lands. The destination is an operand other refactorings
    legitimately rewrite — R12 absorbs a move into it, R08 swaps the keyword
    around it — and R07 judges position, not operands. Keying on the
    destination would make an instruction relocated and re-targeted in the
    same commit unrecognisable in its new place, which is the one thing this
    rule has to see. Every other instruction keeps the shared key.
    """
    if entry.instruction in _FILE_TRANSFER_INSTRUCTIONS:
        key = _transfer_key(entry.value)
        if key is not None:
            _, sources, _ = key
            return (
                entry.instruction,
                tuple(source.rstrip("/") for source in sources),
            )
    return _instruction_key(entry)


def _paired_stages(instructions_a: list, instructions_b: list) -> list:
    """Match the stages of the two states, by alias and then by position.

    Position is counted from the end, for the same reason the FROM rules
    count it from there: the final stage produces the image in both states,
    so it is the one anchor a commit adding or removing a stage leaves fixed.
    """
    stages_a, stages_b = _stages(instructions_a), _stages(instructions_b)
    used, pairs = set(), []
    for position, stage_b in enumerate(stages_b):
        match = None
        if stage_b.alias:
            match = next(
                (index for index, stage_a in enumerate(stages_a)
                 if index not in used and stage_a.alias == stage_b.alias),
                None,
            )
        if match is None:
            from_end = len(stages_b) - 1 - position
            match = next(
                (index for index, stage_a in enumerate(stages_a)
                 if index not in used
                 and len(stages_a) - 1 - index == from_end
                 and not stage_a.alias and not stage_b.alias),
                None,
            )
        if match is not None:
            used.add(match)
            pairs.append((stages_a[match], stage_b))
    return pairs


def _instructions_common_to(body: list, keys: list, common: Counter) -> list:
    """The instructions of one body that the other body also holds."""
    budget = Counter(common)
    kept = []
    for entry, key in zip(body, keys):
        if budget[key] > 0:
            budget[key] -= 1
            kept.append(entry)
    return kept


@rule
def detect_sort_instructions(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R07 — Sort Instructions.

    Directional rule over the instruction order: instructions are rearranged
    so that stable, resource-intensive steps come before frequently modified
    ones, which is what preserves cache validity across rebuilds.

    Judged one stage at a time. Cache invalidation is a property of a single
    layer chain — a FROM starts a new one — so an instruction standing before
    another in a different stage costs nothing, and comparing the file as one
    sequence reads a stage being inlined as though its instructions had been
    sorted. Stages are matched by alias, then by position from the end.

    Within a stage the rule reads only the instructions both states hold,
    per the granularity law. Demanding that the whole stage be a permutation
    made the rule silent on any commit that also added or removed an
    instruction, which is most real commits: a rearrangement accompanied by
    an extraction is still a rearrangement, and the extraction is the other
    rule's finding. Instructions present in only one state are left to it.

    Direction is decided by counting cache inversions — volatile file
    transfers standing before dependency installations. The rearrangement
    qualifies only when that count falls, since moving a COPY ahead of a
    package installation invalidates the expensive layer on every source
    change and is technical debt rather than a refactoring.
    """
    moved_before, moved_after = [], []
    for stage_a, stage_b in _paired_stages(instructions_a, instructions_b):
        body_a, body_b = list(stage_a.instructions), list(stage_b.instructions)
        common = Counter(_sort_identity(e) for e in body_a) & Counter(
            _sort_identity(e) for e in body_b
        )
        kept_a = _instructions_common_to(
            body_a, [_sort_identity(e) for e in body_a], common
        )
        kept_b = _instructions_common_to(
            body_b, [_sort_identity(e) for e in body_b], common
        )
        keys_a = [_sort_identity(entry) for entry in kept_a]
        keys_b = [_sort_identity(entry) for entry in kept_b]
        if not kept_a or keys_a == keys_b:
            continue  # nothing the two states share was rearranged
        if _cache_inversions(kept_b) >= _cache_inversions(kept_a):
            continue  # the rearrangement does not improve cache ordering

        moved_before.extend(
            entry for entry, before, after in zip(kept_a, keys_a, keys_b)
            if before != after
        )
        moved_after.extend(
            entry for entry, before, after in zip(kept_b, keys_a, keys_b)
            if before != after
        )

    if not moved_before:
        return None

    return DetectionResult(
        refactoring_id="R07",
        refactoring_name="Sort Instructions",
        instructions_before=tuple(moved_before),
        instructions_after=tuple(moved_after),
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
    runs_a = _values_of(instructions_a, "RUN")
    runs_b = _values_of(instructions_b, "RUN")

    # Directional: extraction removes shell work from the Dockerfile. This is
    # what separates the refactoring from adding new functionality through a
    # script, and it carries the whole weight of the direction.
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

    # Scripts already invoked before the change. The invocation has to be new:
    # a RUN that merely loses commands while continuing to call a script it
    # already called is a deletion, not an extraction.
    invoked_before = set()
    for value in runs_a:
        invoked_before |= _invoked_scripts(value)

    # Transfers that bring a script in, so the report can name how the script
    # reached the image when the same commit also copies it. Its absence is not
    # disqualifying: the script may have arrived in an earlier commit, or ride
    # in with a directory the build context already carries.
    arrivals = {}
    for entry in instructions_b:
        if entry.instruction in _FILE_TRANSFER_INSTRUCTIONS:
            for path in _script_destinations(entry):
                arrivals.setdefault(path.rsplit("/", 1)[-1], entry)

    for value in runs_b:
        newly_invoked = _invoked_scripts(value) - invoked_before
        if not newly_invoked:
            continue
        script = sorted(newly_invoked)[0]
        caller = Instruction("RUN", value)
        arrival = arrivals.get(script.rsplit("/", 1)[-1])
        reported_after = (arrival, caller) if arrival is not None else (caller,)

        return DetectionResult(
            refactoring_id="R09",
            refactoring_name="Extract RUN Instructions",
            instructions_before=tuple(extracted),
            instructions_after=reported_after,
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
    resolved_a = _resolved_from_parts(instructions_a)
    resolved_b = _resolved_from_parts(instructions_b)
    if not resolved_a or not resolved_b:
        return None

    changed_before = []
    changed_after = []
    for before, parts_before, after, parts_after, position in _pair_from_instructions(
        resolved_a, resolved_b
    ):
        # A FROM naming an earlier stage is a stage reference, not an image;
        # renaming the stage it points at is R14's business, not a base-image
        # substitution.
        stages_before = _stage_identities_before(resolved_a, position)
        stages_after = _stage_identities_before(resolved_b, position)
        if (parts_before.name.lower() in stages_before
                or parts_after.name.lower() in stages_after):
            continue

        # Names are compared canonically, so a reference that only gains or
        # loses the registry and namespace Docker assumes by default — plain
        # `python` against `docker.io/library/python` — is the same image and
        # not a substitution.
        # The entity, and only the entity: a stage renamed in the same commit
        # is R14's finding and must not hide the base-image substitution.
        entity_substitution = (
            parts_before.name != parts_after.name
            and parts_before.flags == parts_after.flags
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

    # Form B: the stage is gone from the file altogether and the transfers that
    # read from it now name a published image instead. The work left in the
    # same sense as form A — into a Dockerfile of its own, built separately —
    # but the reference that used to point at a local stage was rewritten
    # rather than the stage being kept and emptied.
    identities_b = {stage.identity for stage in stages_b}
    for stage in stages_a:
        if not stage.instructions:
            continue  # no body to move out
        if stage.identity in identities_b:
            continue  # the stage survives: form A territory, handled above

        consumers = [
            entry for entry in instructions_a
            if _stage_reference_of(entry) == stage.identity
        ]
        if not consumers:
            continue  # nothing read from it: a plain deletion

        # Sources the stage used to deliver, and who delivers them now.
        delivered = set()
        for entry in consumers:
            operands = _transfer_operands(entry.value)
            if operands is not None:
                delivered |= {source.rstrip("/") for source in operands[0]}

        replacements = []
        for entry in instructions_b:
            reference = _stage_reference_of(entry)
            if reference is None or _names_a_stage(reference, stages_b):
                continue  # still a stage of this file: the work did not leave
            operands = _transfer_operands(entry.value)
            if operands is None:
                continue
            if {source.rstrip("/") for source in operands[0]} & delivered:
                replacements.append(entry)

        if not replacements:
            continue  # nothing external delivers what the stage used to

        return DetectionResult(
            refactoring_id="R11",
            refactoring_name="Move Stage",
            instructions_before=stage.instructions,
            instructions_after=tuple(replacements),
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

    Paths are compared as paths and not as text: a transfer writes to
    ``/tmp/assets/`` while the move it feeds reads ``/tmp/assets``, and the
    trailing separator names no different directory.

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
                 if (ops := _transfer_operands(e.value))
                 and _path(ops[1]) == _path(source)),
                None,
            )
            if origin is None:
                continue
            origin_sources = tuple(
                _path(s) for s in _transfer_operands(origin.value)[0]
            )
            # the same sources now landing straight on the move's destination
            landed = next(
                (e for e in transfers_b
                 if (ops := _transfer_operands(e.value))
                 and _path(ops[1]) == _path(destination)
                 and tuple(_path(s) for s in ops[0]) == origin_sources),
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


def _layout_skeleton(entry: Instruction) -> tuple:
    """What an instruction does, with how it is written stripped away.

    For a RUN this is the ordered sequence of leading commands, one per
    segment. The operands are deliberately left out: a reflow that also
    parameterises an argument is still a reflow, and the parameterisation is
    another rule's finding, reported alongside under the non-exclusion
    principle. Any other keyword falls back to its arguments, so that a
    caller outside R13 gets a defined answer rather than an empty one.

    The sequence is ordered because moving a command is not reformatting. An
    unordered comparison accepts a command relocated to another point in the
    chain, which changes the order the work happens in.
    """
    if entry.instruction != "RUN":
        return tuple(entry.value.split())
    return tuple(
        segment.split()[0]
        for segment in _shell_segments(entry.value)
        if segment.split() and not _SHELL_DIRECTIVE.match(segment)
    )


def _work_survived_reflow(used: list, after: Instruction) -> bool:
    """Whether the same work crossed the reflow, allowing parameterisation.

    The command skeleton alone does not settle it: it names the commands and
    not what they operate on, so an instruction that gained a package while
    being split across lines would satisfy it. The words decide.

    Identical words are a pure reflow, whether one instruction was rewritten
    or several were consolidated into one. Otherwise the difference has to
    be a substitution and not an edit: words must have left as well as
    arrived, which rules out an argument simply added or simply dropped, and
    at least one of the arriving words must be a variable reference, which
    is what a parameterisation looks like. Swapping one literal for another
    satisfies neither and is a content edit.
    """
    source_words = Counter()
    for entry in used:
        source_words += _run_commands(entry.value)
    after_words = _run_commands(after.value)
    if after_words == source_words:
        return True

    departed = source_words - after_words
    arrived = after_words - source_words
    if not departed or not arrived:
        return False  # an argument was added, or removed: a content edit
    return any(_VARIABLE_REFERENCE.search(word) for word in arrived)


def _reflowed_from(available: list, after: Instruction) -> list:
    """Consecutive instructions reflowed into ``after``, or nothing.

    One instruction may be reflowed on its own, or several may be reflowed
    into one; consolidating and reformatting in the same commit is ordinary,
    and each is a separate finding on the same instruction. Candidates are
    taken consecutively and in file order, because that is the order a
    consolidation preserves.

    At least one source must be written differently from the result: without
    that the typography did not change and there is nothing to report.
    """
    target = _layout_skeleton(after)
    if not target:
        return []
    for start in range(len(available)):
        accumulated: tuple = ()
        used = []
        for candidate in available[start:]:
            accumulated += _layout_skeleton(candidate)
            used.append(candidate)
            if len(accumulated) > len(target):
                break
            if accumulated != target:
                continue
            if any(entry.layout != after.layout for entry in used):
                if _work_survived_reflow(used, after):
                    return used
            break
    return []

@rule
def detect_update_run_instruction(
    instructions_a: list, instructions_b: list
) -> Optional[DetectionResult]:
    """R13 - Update RUN Instruction.

    The refactoring changes how an instruction is written, not what it does:
    split a long instruction across backslash continuations, or sort its
    arguments alphanumerically. The rule recognises two forms of that, and a
    commit exhibiting either is reported.

    *The words are the same and the text is not.* Reordering arguments and
    respacing them leave the multiset of words untouched, so a RUN whose words
    match one that disappeared is the same RUN, rewritten. Adding, removing or
    re-versioning a package changes the multiset and is a content edit, never
    reported here. This form needs no change of typography, since sorting a
    package list on one line changes none.

    *The typography changed and the commands survived it.* The class an
    instruction is written in - one line, continuations, heredoc - is recorded
    at parse time, and a change of class is the positive evidence that a
    reflow happened. What must then be shown is that the same work crossed it,
    which ``_layout_skeleton`` states as the ordered sequence of commands.
    Several RUNs reflowed into one are covered, since consolidating and
    reformatting in the same commit is ordinary and each is its own finding.

    Both forms read RUN and nothing else. Other keywords are written across
    continuations too - a LABEL carrying five annotations, an ENV carrying
    ten - but the catalogue defines this refactoring over RUN instructions,
    and a rule that reported a reflowed LABEL would be reporting a
    refactoring the catalogue does not contain.

    The second form tolerates operand differences that the first rejects, and
    that is deliberate: a commit that reflows a RUN while replacing a literal
    with a variable has reformatted it, whatever else it also did. The
    tolerance is bounded by the requirement that the typography changed, so an
    operand edit on its own is never mistaken for a reflow. It remains the
    looser of the two: a single-command RUN that is reflowed and re-argued at
    once is reported, and the evidence carries both texts so the reader sees
    what else moved.
    """
    changed_before, changed_after = [], []

    # --- Same words, different text.
    runs_a = _values_of(instructions_a, "RUN")
    runs_b = _values_of(instructions_b, "RUN")
    surviving = set(runs_b)
    available = [value for value in runs_a if value not in surviving]
    for after in runs_b:
        if after in runs_a:
            continue  # unchanged text: nothing was rewritten here
        commands_after = _run_commands(after)
        match = next(
            (value for value in available if _run_commands(value) == commands_after),
            None,
        )
        if match is None:
            continue
        available.remove(match)
        changed_before.append(Instruction("RUN", match))
        changed_after.append(Instruction("RUN", after))

    # --- Different typography, same commands.
    identities_a = {(entry.instruction, entry.value) for entry in instructions_a}
    identities_b = {(entry.instruction, entry.value) for entry in instructions_b}
    already = {entry.value for entry in changed_after}
    gone = [
        entry
        for entry in instructions_a
        if entry.instruction == "RUN"
        and ("RUN", entry.value) not in identities_b
    ]
    for after in instructions_b:
        if after.instruction != "RUN":
            continue
        if ("RUN", after.value) in identities_a:
            continue  # the instruction is untouched
        if after.value in already:
            continue  # already reported by the first form
        used = _reflowed_from(gone, after)
        if not used:
            continue
        for entry in used:
            gone.remove(entry)
            changed_before.append(entry)
        changed_after.append(after)

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
    resolved_a = _resolved_from_parts(instructions_a)
    resolved_b = _resolved_from_parts(instructions_b)
    if not resolved_a or not resolved_b:
        return None

    changed_before = []
    changed_after = []
    for before, parts_before, after, parts_after, _position in _pair_from_instructions(
        resolved_a, resolved_b
    ):
        if before == after:
            continue
        # The image itself must be the same image, so a base substitution stays
        # R10's finding. Its tag is free to change in the same commit: that is
        # R02's dimension, and demanding it be untouched would silence this
        # rule on every commit that pins a version while renaming a stage.
        image_untouched = (
            parts_before.name == parts_after.name
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
