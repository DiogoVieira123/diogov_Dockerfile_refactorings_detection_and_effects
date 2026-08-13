# Implementation Log

Chronological record of the prototype implementation, one entry per component
or non-trivial problem. Feeds the thesis Implementation chapter (Chapter 6).

## Test inventory — current state

The entries below are a diary: each records the suite size at the time it was
written, so the figures inside them grow as the work progressed and are not
meant to be read as current. This table is the single current inventory,
measured on 2026-08-11.

| Module / Component | Test file | Tests | Notes |
|---|---|---:|---|
| VCS Connector | `test_vcs_connector.py` | 8 | RF1, RNF4 |
| VCS Connector (integration) | `test_vcs_connector_getting_started.py` | 1 | Experiment 3 replication; skipped unless `GETTING_STARTED_REPO` is set |
| Detection Engine | `test_detection_engine.py` | 119 | 111 across R01–R14, 8 cross-cutting (RNF3 ×3, parsing ×5) |
| Image builder (Stage 2 preparation) | `test_image_builder.py` | 18 | RNF4 |
| Performance Analyzer | `test_performance_analyzer.py` | 15 | RF4, RNF1, RNF4 |
| Data Extractor | `test_data_extractor.py` | 43 | RF5, RF6, RNF2, RNF4, RNF5. 41 functions; one is parametrised over 3 cases |
| Report Generator | `test_report_generator.py` | 35 | RF7, RNF5 |
| Pipeline orchestrator + CLI | `test_pipeline.py` | 28 | Historical commit export, stage sequencing, Stage 2 concurrency, image and temp-tree lifetime, exit codes. 24 functions; one is parametrised over 5 cases |
| **Total** | | **267 collected** | **263 passing, 4 skipped** |

Per rule in the Detection Engine: R01 9, R02 16, R03 9, R04 6, R05 5, R06 6,
R07 6, R08 10, R09 10, R10 7, R11 6, R12 7, R13 7, R14 7.

The four skipped tests are the end-to-end ones, each guarded by a `skipif`: the
Experiment 3 replication needs a local clone of `docker/getting-started`, and
the image builder, Performance Analyzer and Data Extractor end-to-end tests need
a reachable Docker daemon. All four run and pass under WSL2 with the daemon
available; the skips are a property of the Windows host, not of the tests.

Package coverage: 98% (860 statements, 21 uncovered).

---

## 2026-08-13 — Historical commit contexts for the image builds

**Purpose.** Build each Dockerfile state against its own commit's file tree
instead of against the working tree, removing the soundness limitation recorded
with the orchestrator.

**The defect.** The orchestrator passed one context directory — the repository
root as it stands now — to both builds. Two consequences, both silent:

* a file that changed alongside the refactoring reached both measurements, so
  the size delta carried that difference as well as the refactoring's;
* the earlier state was built against files that may not have existed at its
  commit, which is not a measurement of that state at all.

**Implementation.** `pipeline.commit_context(repository, sha)` is a context
manager that exports one commit's tree into a temporary directory:

* `repo.archive(stream, treeish=sha, format="tar")` writes the tree as a tar
  stream in memory. It touches neither the working tree nor the index, which
  keeps the export consistent with the blob-level access the VCS Connector
  already uses (RF1) — nothing is checked out and the repository is left
  exactly as it was found.
* The archive is unpacked with `extractall(destination, filter="data")`. The
  filter rejects absolute paths, parent-directory traversal, links pointing
  outside the destination and device nodes, so a crafted repository cannot
  write beyond the temporary directory.
* `tempfile.TemporaryDirectory` is created outside the `try` and cleaned up in
  its `finally`, so the directory is removed whether the export fails, the
  caller raises, or the block ends normally.

`build_image_pair` now takes `context_before` and `context_after` rather than a
single `context_path`, since the whole point is that the two builds no longer
share a context. `run_analysis` opens both exports and the build in one
`contextlib.ExitStack`, which holds the directories for as long as the builds
need them and unwinds in reverse on the way out: images first, then the trees
that produced them.

**Failure handling.** A new `CommitContextError` covers a repository that
cannot be opened, a treeish Git does not recognise, and an archive that cannot
be unpacked, so a raw GitPython or tarfile error never escapes (RNF4). It maps
to exit code 3 at the command line, alongside the other preparation failures.

**Removed.** The `--context` command-line flag and the `build_context`
parameter. With per-commit contexts, the only thing that option could do was
reintroduce the defect this change fixes, and an option whose sole effect is to
make the measurement unsound is worse than no option.

**Testing.** 12 tests added to `tests/test_pipeline.py`. Seven exercise
`commit_context` against a real two-commit repository built by a fixture, whose
commits differ in file *content* and in which files exist: the export carries
the tree as it was at that commit and omits a file added later, an abbreviated
SHA is accepted, the directory is removed on exit and when the caller raises,
the working tree is left untouched, an unknown commit and a path that is not a
repository each raise `CommitContextError`. Five cover the wiring: both trees
exported in order, the two builds receiving different contexts, the exports
preceding the build, both trees removed after the images, and both removed even
when a Stage 2 component fails.

**End-to-end proof.** A repository was built with two commits whose committed
`payload.txt` is 6 bytes, after which the working tree copy was replaced with a
405,264-byte file that was never committed. Analysed through the command line,
the images measured 3,632,156 and 3,632,741 bytes — the size of the committed
payload. Had the working tree been used, both would have carried the extra
400 KB and the measurement would have been meaningless. No temporary directory
survived the run.

**Suite.** 263 tests passing, 4 skipped. Package coverage 98%.

---

## 2026-08-13 — Pipeline orchestrator and command-line entry point (Section 5.1)

**Purpose.** Chain the five components into a runnable analysis. Until now each
component was a library with a public function and none imported another, so
the pipeline existed as a design and as throwaway validation scripts, but not
as code in the repository. This closes that gap.

**Files.** `src/pipeline.py` holds the orchestration as an importable function;
`main.py` at the repository root is the command-line entry point. The split
keeps the sequencing testable without invoking a process.

**Key design decisions.**

*The orchestrator owns the sequence, the components stay ignorant of it.* Every
component still knows nothing of its neighbours. The ordering, the parallelism
and the resource lifetime live in one place, which is what keeps the components
independently testable and independently replaceable.

*Stage 2 concurrency is the orchestrator's to arrange.* The two components are
submitted to a two-worker pool against the same image references. Both futures
are resolved before either result is used, so a failure in one does not leave
the other running past the exit of the preparation context. The images are
built once, before the stage begins, and removed when its context closes —
whatever happened inside it.

*Provenance is gathered after the measurements, not before.* The Trivy
vulnerability database is downloaded into the shared cache during the first
scan, so a version query made beforehand would report it as absent. Collecting
the versions inside the preparation context, after Stage 2, makes the recorded
database version the one the scans actually used (RNF5).

*Exit codes make RNF4's distinct exceptions observable.* Each component's
exception maps to its own code — 1 VCS Connector, 2 Detection Engine parsing,
3 image preparation, 4 Performance Analyzer, 5 Data Extractor, 6 report
writing. Without this the distinct exception types collapse into a single
non-zero exit at the process boundary and the diagnostic value is lost.

**Problem and solution — the build context.** The VCS Connector retrieves
Dockerfile content at blob level without a checkout (RF1), and no component
reconstructs a full tree, yet a Dockerfile carrying COPY needs its context
files to build. The orchestrator therefore takes the build context from the
working tree as it stands, defaulting to the repository root and overridable
with `--context`. This is a real limitation and is documented in the function's
docstring: for the analysis to be sound the files a COPY reads must be
equivalent across the two commits, and where they are not, the size delta
carries that difference alongside the refactoring's. Reconstructing the tree at
each commit would extend the VCS Connector beyond RF1 and was not done.

**Testing.** 19 tests in `tests/test_pipeline.py`, with all five components
replaced by fakes so the wiring is exercised without a daemon and without
repeating what each component's own suite covers: stage ordering, both Stage 2
components receiving the same image references, the images alive during Stage 2
and removed after, the tracked Dockerfile path reaching the VCS Connector, the
build context defaulting to the repository and honouring an override, the three
artifacts written, the report carrying the detection and both SHAs, a Stage 2
failure still removing the images, no image built when retrieval fails, the CLI
returning zero and printing the summary, and each of the five failures mapping
to its own exit code.

**End-to-end verification.** A throwaway Git repository was created under WSL
with two commits — the R09 catalogue pair, `Dockerfile.before` then
`Dockerfile.after` with `setup.sh` — and analysed exactly as a reader would:

```
python3 main.py /tmp/demo 1ae60d5 db807e7 -o /tmp/out
```

It reported `R09 Extract RUN Instructions` with ΔSize +410, ΔCVEs +0,
ΔWarnings +0, ΔInstr +1, exited 0, and wrote four files: `impact_report.json`
(2,608 B), `human_readable_summary.txt` (2,393 B), and under `raw_data/` the
retained evidence (50,647 B of Trivy output, 34 B of Hadolint). The environment
block recorded Docker Engine 29.1.3, Hadolint 2.14.0, Trivy 0.72.0, Trivy
database 2026-08-13T19:12:03Z, dockerfile-parse 2.0.1, GitPython 3.1.50, Docker
SDK 7.1.0 and Python 3.14.4.

A first attempt failed on a transient Trivy database download error, which
surfaced as `DataExtractorError` naming the failing scan and exited 5 — the
RNF4 contract and the exit-code mapping both behaving as specified against a
real fault rather than a simulated one.

**Suite.** 254 tests passing, 4 skipped. Package coverage 98%.

---

## Detection Engine — RNF3 extensibility, acceptance criterion exercised

* **Date:** 2026-08-10
* **Requirement:** RNF3 — "a new detection rule can be added to the registry and
  exercised end to end without editing any existing rule or any downstream
  component".
* **Status:** Proven by test. No production change was made.

The registry mechanism — the `@rule` decorator appending to `_RULES` — had been
in place since the first rule and all fourteen catalogue rules were added
through it, but nothing exercised the criterion itself. Three tests now do,
all in `tests/test_detection_engine.py`:

* `test_rnf3_a_new_rule_is_exercised_end_to_end_without_editing_the_engine`
  defines a fictitious rule (`R99 — Add HEALTHCHECK`) entirely inside the test
  file, registers it through the public decorator, and asserts three things:
  that the decorator alone placed it in the registry, that `detect_refactorings`
  runs and reports it against a real Dockerfile pair, and that it takes the last
  registry position so the reporting order of the catalogue rules is undisturbed
  by its addition.
* `test_rnf3_the_existing_rules_keep_working_alongside_a_new_one` covers the
  other half of the criterion. It measures the detection of the R01 pair before
  registering a new rule and after, and requires
  `with_new_rule == baseline + ["R99"]`: adding a rule must neither alter nor
  suppress any existing one.
* `test_rnf3_the_registry_is_restored_between_tests` verifies the isolation
  holds, running without the fixture and requiring that no `R99` survives.

A `registry_restored` fixture snapshots `_RULES` by value and repairs the list
**in place** (`_RULES[:] = snapshot`) in its `finally`. Repairing in place rather
than rebinding matters: the `@rule` decorator closes over that list object, so
replacing it would break registration for the remainder of the session.

Conformance was verified rather than asserted: `git diff` and `git status`
against `src/detection_engine.py` are both empty, so no line of the production
module was touched, which is the Open-Closed Principle the requirement demands.
Isolation was confirmed twice — by the third test, and by an external check that
runs the whole suite and then imports the engine, finding 14 registered rules
and no residual `R99`. The suite also passes with `-p no:randomly`, ruling out
order dependence.

This closes the gap the conformance audit had recorded against RNF3, which had
the mechanism in place but the criterion unexercised.

---

## 2026-08-11 — Coverage audit: confirmation and one correction

**Purpose.** Re-run the coverage suite and confirm the figures previously
recorded, checking specifically whether the uncovered lines are still the ones
described.

**Result — figures confirmed, unchanged.**

| Module | Stmts | Miss | Cover | Missing |
|---|---|---|---|---|
| `data_extractor.py` | 121 | 2 | 98% | 373–374 |
| `detection_engine.py` | 422 | 13 | 97% | 96–97, 164, 292, 306, 311, 353, 385, 391, 729, 902, 1015, 1090 |
| `image_builder.py` | 80 | 2 | 98% | 256–257 |
| `performance_analyzer.py` | 38 | 0 | 100% | — |
| `report_generator.py` | 94 | 0 | 100% | — |
| `vcs_connector.py` | 25 | 0 | 100% | — |
| **Package** | **780** | **17** | **98%** | |

232 tests passing, 4 skipped, at the moment of this measurement — the figure
before the three tests added below, which took it to the current 235.

**Data Extractor — confirmed as recorded.** Lines 373–374 are exactly the
`except Exception` guarding the dockerfile-parse call and the
`DataExtractorError` it raises. They remain the module's only uncovered
statements, and the earlier audit established the branch is unreachable in
practice because dockerfile-parse does not raise on malformed content: it
accepts arbitrary text and treats the first word of each line as an
instruction.

**Correction — the package figure has a different composition.** The
module-level attribution to a single unreachable `except` holds for the Data
Extractor, but does not generalise to the package. Classifying all 17
uncovered statements:

* *Unreachable in practice (4).* `data_extractor.py` 373–374 and
  `detection_engine.py` 96–97, both the same `except` around dockerfile-parse.
* *Reachable only through an external fault (2).* `image_builder.py` 256–257,
  the handler for a daemon that answers but reports no version.
* *Reachable, working, and untested (2) — since closed, see below.*
  * `detection_engine.py` 164 — digest parsing in `_parse_from_value`.
    `FROM alpine@sha256:abc123 AS build` resolves to
    `name='alpine' digest='sha256:abc123' alias='build'`, and R02 fires
    correctly on a digest-pinned FROM that gains a tag. No test covered a
    digest-pinned base image anywhere in the suite.
  * `detection_engine.py` 385 — the `./script.sh` invocation form in
    `_invokes_script`. R09 detects correctly when the extracted script is
    called as `RUN ./setup.sh` rather than by absolute path. No test used that
    form.
* *Rule guard branches (9).* `detection_engine.py` 292, 306, 311, 353, 391,
  729, 902, 1015 and 1090, defensive `return None` and `continue` statements
  inside individual rules. Not individually exercised; no claim is made here
  that they are unreachable, only that no test reaches them.

**Significance.** The two reachable-and-untested lines were the finding worth
recording. They are not defensive code: they implement behaviour the engine
relies on — digest-pinned base images and the relative invocation form — and a
regression in either would have passed the suite silently.

**Gap closed.** Three tests were added to `tests/test_detection_engine.py`, in
the sections of the rules they concern, with no production change:

* `test_r02_detects_a_tag_added_to_a_digest_pinned_base` — a FROM carrying both
  a digest and a tag, where the tag is added and the digest is unchanged, so
  the entity is preserved and R02 fires. This is what exercises line 164: the
  digest must survive the parse rather than being read as part of the image
  name.
* `test_r02_not_triggered_when_the_digest_itself_changes` — the negative
  counterpart, added alongside because a rule that fires on digest-pinned
  images needs its boundary pinned too: a different digest is a different
  image, so entity preservation fails and no tag update is reported.
* `test_r09_detects_a_script_invoked_by_relative_path` — `RUN ./setup.sh`, the
  third invocation form alongside the absolute path and the interpreter call,
  exercising line 385.

**Resulting figures.** `detection_engine.py` from 13 uncovered statements to
11, the package from 17 to 15. The package percentage stays at 98% and the
Data Extractor at 98% with lines 373–374, both unchanged. 235 tests passing, 4
skipped.

**No regression from the previous record.** The percentages and missing-line
sets before these additions were identical to those logged for the Report
Generator entry of 2026-08-11. The correction above concerns how the figure was
characterised, not the figure itself.

---

## 2026-08-11 — Report Generator (RF7, RNF5) + system-wide conformance verification

**Purpose.** Implement the terminal pipeline stage as three written artifacts,
and verify every component against the design chapter, including the exact
delta nomenclature.

### Task 1 — Report Generator

**Outputs.** `generate_report()` writes, into a caller-supplied directory:

* `impact_report.json` — before and after value of every metric, the four
  deltas, the per-severity CVE vector, the reproducibility block, and pointers
  to the retained artifacts;
* `raw_data/trivy_raw.json` and `raw_data/hadolint_raw.json` — the source
  analysis artifacts the Data Extractor retained, each keyed by state so the
  before and after evidence stay distinguishable;
* `human_readable_summary.txt` — the same content arranged for direct review.

**Key design decisions.**

*Aggregation, not interpretation.* The component pairs the catalogue identifier
of each detection with the four measured deltas exactly as obtained, adding no
expected direction, no dimensional label and no judgement. A test enforces this
negatively, asserting the serialised report contains none of "performance",
"security", "maintainability", "improvement", "degradation", "expected",
"better" or "worse" outside the sign-convention note.

*Deltas are carried, not recomputed.* Each delta comes from the component that
measured it. Two independent computations of one quantity could disagree, and
the measuring component is the authority on its own metric.

*Artifacts beside the report, not inside it.* The retained Trivy output runs to
tens of kilobytes — 50,648 bytes for the R09 pair — so embedding it would bury
the structured output. The JSON references the files by name and they live one
directory away, which keeps the report readable while the evidence stays with
it. Each file is a single JSON document keyed by state, with each state's text
embedded as a parsed value rather than a quoted string, so the artifact stays
machine-readable end to end. Output that does not parse is kept as a raw string
rather than discarded: a tool emitting something unexpected must not cost the
evidence.

*One derivation, two formats.* `to_text` reads the report's own fields and
recomputes nothing, so the JSON and the summary cannot drift apart. A test
tampers with a field and asserts the tampered value reaches the summary.

*LF endings everywhere.* Every artifact is written UTF-8 with LF, so a report
produced on Windows is byte-identical to one produced on Linux and a re-run can
be compared with `diff`.

*An empty detection list is a valid report.* No supported refactoring
recognised is a result, not a failure: the section is empty and the four
metrics are still measured and reported.

**Testing.** 35 tests, 100% coverage of the module. Beyond the metric and
RNF5 content: the three artifacts written to the expected paths, the output
directory created when absent, one raw file per tool, both states
distinguishable inside each, the retained findings accounting for the counted
values, non-JSON output preserved, the JSON pointing at the raw files, the
summary naming them, and LF endings in both text artifacts.

**Full pipeline verification.** Run end to end against the R09 catalogue pair
under WSL with a real daemon: detection, build, both Stage 2 components
dispatched concurrently, and the report. Produced `R09 Extract RUN
Instructions` with ΔSize +416, ΔCVEs +0, ΔWarnings +0, ΔInstr +1, an
environment block naming Docker Engine 29.1.3, Hadolint 2.14.0, Trivy 0.72.0,
Trivy database 2026-08-11T19:13:09Z and dockerfile-parse 2.0.1, and 50,648
bytes of Trivy evidence plus 34 bytes of Hadolint evidence under `raw_data/`.
ΔSize differs from the recorded +417 by the environmental variation documented
in the Performance Analyzer entry.

A transient Trivy database download failure during the first attempt surfaced
as `DataExtractorError` naming the failing scan, which is the RNF4 contract
behaving as specified against a real fault rather than a simulated one.

### Task 2 — Conformance verification

Verified programmatically against `DESIGN_CHAPTER.md` rather than by reading.

**Correction applied.** The Data Extractor exposed its instruction delta as
`delta_instructions` while RF7 names it `delta_logical_instructions`. Renamed
across the component and its tests, so the name is identical from the point of
measurement to the point of serialisation.

**Verified conformant.**

| Component | Checked | Result |
|---|---|---|
| VCS Connector | RF1 blob-level access, no working tree | conformant |
| Detection Engine | RF2, RF3, RNF3; 14 rules in a declarative registry | conformant |
| Performance Analyzer | RNF1: `image.attrs["Size"]` via the SDK, no CLI | conformant — no `subprocess` in the module |
| Data Extractor | Section 4.6 retention of raw artifacts | conformant — `raw_trivy`, `raw_hadolint` |
| Report Generator | RF7 structured output, RNF5 provenance | conformant |
| All components | RF1 single-file scope | no Dockerfile discovery anywhere |

**Discrepancies left standing, both documentation-side.**

*`delta_hadolint`.* RF7 lists the delta keys as `delta_size, delta_warnings,
delta_hadolint, delta_logical_instructions`. There is no `delta_hadolint`
quantity in the design — the four metrics are size, CVEs, warnings and logical
instructions — and the list has no key for CVEs at all. The author identified
this as an error in the chapter text on 2026-08-07 and approved `delta_cves` in
the code, which is what the code emits. Implementing the literal chapter name
would encode a known error and leave the CVE delta unnamed, so it was not done.
The chapter line remains to be retouched.

*`SizeMetric`.* Table 4.10 describes the Performance Analyzer as outputting
`MetricSet_A, MetricSet_B (size in bytes)`, while the code names that structure
`SizeMetric`. Renaming it to `MetricSet` would collide with the Data
Extractor's `MetricSet`, which carries entirely different fields, and the two
would have to be disambiguated by module at every use in the Report Generator.
The distinct name was kept for clarity and is recorded here as a deliberate
divergence from the table's wording rather than from its meaning.

**Suite.** 235 tests passing, 4 skipped on Windows. Package coverage 98%.

---

## Component and Integration Testing Strategy

Dedicated unit tests were implemented for each individual pipeline component to
validate its isolated behavior, complemented by integration tests verifying the
correct interaction and data flow between modules. This structured testing
approach guarantees the internal integrity of the execution pipeline and
ensures strict compliance with all functional and non-functional requirements.

---

## Design Decision & Scope — Single-Dockerfile Refactoring Focus & Future Roadmap

* **Date:** 2026-08-10
* **Context:** Scope definition of the Detection Engine and evolution strategy.
* **Architectural decision:** The prototype and its implemented rule set
  (R01–R14) focus explicitly on **single-Dockerfile refactorings**.
* **Technical justification:**
  * The overwhelming majority of the catalogue's rules — R01, the consolidation
    of RUN instructions, among them — operate in isolation over the internal
    structure of a single Dockerfile, detecting and optimising local
    improvements in syntax and organisation.
  * The exclusive focus on a single Dockerfile is a conscious scope limitation,
    designed to cut ambiguity off at the root and guarantee the reliability of
    the current prototype.
  * While the generality of the rules covers local transformations, more
    complex structural operations — such as R11, Move Stage, which extracts a
    build stage into a separate Dockerfile — evidence the transition to
    multi-file scenarios. Cases involving the simultaneous, coordinated or
    interdependent refactoring of several Dockerfiles in one commit demand a
    relational analysis complexity that exceeds the scope of this research
    prototype.
* **Roadmap (future work):**
  * Expansion of the architecture to support repositories with **multiple
    Dockerfiles**, natively covering inter-file refactoring operations such as
    R11.
  * Implementation of explicit file mapping mechanisms (*input mapping*) to
    resolve ambiguities in complex repositories.
  * Evolution of the detection engine to support coordinated relational
    analysis across different Dockerfiles within a single commit.

**Verified against the implementation.** The decision matches the code as
built. `detect_refactorings(dockerfile_a, dockerfile_b)` takes two strings and
nothing else; all fourteen rule functions receive exactly two instruction
lists, one per state of one file; and the engine performs no filesystem access
at all, so a second Dockerfile is unreachable rather than merely unused. The
same property holds downstream in the Data Extractor, whose ΔInstr consequence
for R11 is recorded in the *Edge Case: Divergence in Experiment R11* entry of
that component's section, and in Section 4.9 of the thesis.

---

## Requirement Resolution — RF5 acceptance criteria aligned with Appendix C

* **Date:** 2026-08-10
* **Status:** Resolved — no code change required.
* **Finding that prompted it:** The conformance audit reported that the RF5
  acceptance criterion "PoC-4 test — correctly computes the warning delta,
  yielding −1 for DL3020" cannot be satisfied by the implementation, because
  DL3020 is absent from the 47-rule maintainability screen.
* **Resolution:** The code stands exactly as it was. It already honoured the
  architectural design: Appendix C derives the screen by dimensional exclusion,
  removing the rules that target security surfaces so that the maintainability
  metric does not duplicate what ΔCVEs already measures, and DL3020 — the
  security smell of ADD — is excluded by that criterion. The divergence was in
  the requirement text, which carried an acceptance criterion predating the
  screen, and the reference to PoC-4 (DL3020) was removed from the manuscript.
* **Criteria that remain and are met:** PoC-2, ΔWarnings = −1 for DL3007, a
  rule the screen does contain, covered by
  `test_eliminating_one_rule_violation_yields_a_delta_of_minus_one`; and PoC-3,
  the CVE delta read from the Trivy JSON.
* **Repository note:** `DESIGN_CHAPTER.md`, the Markdown working copy of the
  chapter held in this repository, still carries the PoC-4 sentence at line 132
  and has not yet received the same edit as the manuscript.

---

## 2026-08-10 — Data Extractor: retention of source analysis artifacts (RNF5)

**Purpose.** Retain the raw JSON that Hadolint and Trivy emit, rather than
discarding it once the counts have been taken.

**Reason.** RNF5 requires reproducibility to rest not only on recorded tool
versions but on "the capability to retain the source analysis artifacts
generated by external tools during the extraction phase", and names the
retained artifacts in its acceptance criterion. The conformance audit found
this the one acceptance criterion unmet in code: the component counted the
findings and let the output go.

**Key design decisions.** `ExtractionResult` gains `raw_hadolint` and
`raw_trivy`, each a mapping from state to the tool's output text. The text is
decoded from the bytes the tool wrote and kept verbatim; it is never
re-serialised from the parsed object, which would silently normalise key order
and whitespace and stop it being the artifact. Retaining it costs nothing at
extraction time, since `_run` already returns the bytes and the parsed object
was built from them.

**Testing.** Three tests: both states present for both tools with the text
matching what the tool emitted; a deliberately quirky payload — unusual spacing
and reversed key order — surviving byte for byte while still parsing to the
right count; and the retained text accounting for exactly the identifiers that
were counted. Verified against the real tools on the R09 catalogue pair, which
retained 24,227 and 24,470 bytes of Trivy output for the two states. Module
suite at 41 tests, 98% coverage; full suite 197 passing, 4 skipped.

**Downstream note.** The acceptance criterion asks that every generated report
*contain* the retained artifacts. The Report Generator was removed on
2026-08-10 at the author's instruction, so the artifacts are retained and
exposed at the component boundary but not yet carried into a report. The
criterion is therefore satisfied in the extraction phase and pending in the
reporting phase.

**Most relevant snippet.**

```python
        raw_hadolint={
            "before": outputs["lint_before"].decode("utf-8", errors="replace"),
            "after": outputs["lint_after"].decode("utf-8", errors="replace"),
        },
        raw_trivy={
            "before": outputs["scan_before"].decode("utf-8", errors="replace"),
            "after": outputs["scan_after"].decode("utf-8", errors="replace"),
        },
```

---

## 2026-08-10 — Data Extractor: audit follow-ups (RNF4, RNF5)

**Purpose.** Close the three findings of the Data Extractor audit.

**Problems and solutions.**

*Unhandled AttributeError on a malformed Trivy report.* The traversal of
`Results` and `Vulnerabilities` assumed every nested member was an object, so a
truncated report raised a raw `AttributeError` from the middle of the walk
instead of the `DataExtractorError` that RNF4 requires of every external tool
failure. The Hadolint side was already guarded; the Trivy side was not. The
traversal is now wrapped, converting `AttributeError` and `TypeError` into a
`DataExtractorError` naming the shape problem. Three parametrised regression
tests cover a non-object result, a non-object vulnerability and an integer
where a vulnerability was expected.

*`tool_provenance()` untested.* The function that satisfies RNF5 had no test at
all, which is the worst place in the module for a silent regression: a change
to the `trivy version` schema would return the database version as "not yet
downloaded" without anything failing, exactly as happened once during
development. Six tests now cover it — all three versions reported, the query
made against the shared database cache, an unpopulated cache reported as
unavailable rather than invented, a missing docker command, malformed JSON and
an unexpected shape.

*A comment contradicting the code.* The comment above the tool image constants
claimed they were pinned, while both are untagged and resolve to `:latest`. The
images stay untagged, which is a deliberate choice to preserve exact parity with
the extended-catalogue experiments — a pinned tag here would measure with a
different tool build than the one that produced the recorded values — and the
comment now states that choice, its cost, and the fact that `tool_provenance()`
recording the version in every report is what compensates for it (RNF5).

**Testing.** The module's suite grew from 29 to 40 tests, and its coverage from
91% to 98%. The two statements still uncovered are the `except` around
dockerfile-parse, which the audit established is unreachable in practice because
the parser does not raise on malformed content.

---

## 2026-08-10 — Data Extractor (RF5, RF6, RNF2, RNF4, RNF5)

**Purpose.** Stage 2 component, running in parallel with the Performance
Analyzer. It receives the two Dockerfile states and the references to the two
images the preparation phase built, and returns three signed deltas: ΔCVEs,
ΔWarnings and ΔInstr.

**Technology.** Trivy and Hadolint as containers (`aquasec/trivy`,
`hadolint/hadolint`), validated in Experiment 2, plus dockerfile-parse 2.0.1
for the instruction count. Both tools are invoked in JSON mode and their
heterogeneous schemas are normalised here into one metric representation.

**Reason for the choice.** The tools are invoked through the same commands the
extended-catalogue experiments use, so the values this component produces are
directly comparable with the recorded ones. This is the one place where the
prototype shells out to the Docker CLI: the CLI was rejected for image size
because it rounds, but nothing is being read from it here beyond a container's
stdout, and matching the validated experiment protocol byte for byte is worth
more than uniformity with the SDK used elsewhere.

**Key design decisions.**

*The component measures and nothing else.* It does not build images and does
not remove them — both belong to the preparation phase — and the images arrive
as identifiers consumed strictly read-only. It never reads a value produced by
the Performance Analyzer: its three metrics are computed without ΔSize, just as
ΔSize is computed without them. Tests assert the boundary directly, checking
that no emitted command contains `build`, `rmi` or `remove`.

*Independent parsing.* `count_logical_instructions` uses dockerfile-parse
directly and imports nothing from the Detection Engine. The two have different
obligations — the engine needs each instruction's keyword and argument string
to decide a refactoring, this component needs only how many there are — and
coupling them would let a change to detection move a maintainability metric. A
test reads this module's own source and fails if the string `detection_engine`
appears in it, so the coupling cannot reappear by oversight.

*The 47-rule screen as a declarative list.* `MAINTAINABILITY_SCREEN` holds the
Appendix C rules as data, inspectable and revisable without touching the
parsing logic. Its contents were verified programmatically to be set-identical
to the `HADOLINT_FILTER` of the catalogue verification scripts. Every finding
of a screened rule counts, including repeated violations of the same rule on
different lines: the metric is the global sum of maintainability violations,
not the number of distinct rules violated.

*Distinct identifiers, deduplicated globally.* RF5 counts distinct
vulnerability identifiers rather than occurrences, so deduplication spans the
whole Trivy report rather than each result: the same CVE reported for two
packages contributes one identifier. The first severity seen for an identifier
is the one kept, so a CVE listed twice cannot inflate a tier. A vulnerability
whose severity is absent or outside the known tiers still counts towards the
total, so the tiers never exceed it but may sum to less.

*ΔCVEs by severity tier.* RF5 requires the CVE delta "by severity tier", so
`delta_cves` is accompanied by `delta_cves_by_severity` across CRITICAL, HIGH,
MEDIUM, LOW and UNKNOWN. The single total remains the headline figure the
Report Generator aggregates.

*Internal concurrency.* The four external invocations — two Trivy scans and two
Hadolint analyses — are dispatched together, since none depends on another's
result and the scans dominate elapsed time. Every future is resolved before the
first failure is raised, so no container is left running behind an early
return. The instruction count runs in-process and needs no container.

*A shared Trivy database cache.* Trivy keeps its vulnerability database in a
cache directory that a `--rm` container loses on exit. Without a persistent
volume every scan re-downloads the database and, more importantly for RNF5,
`trivy version` reports no database metadata at all — the first implementation
returned the database version as "unknown" for exactly this reason. A named
volume shared by the two scans and the version query fixes both: the database
is downloaded once, and the version recorded is the one the measurements
actually used. Verified end to end, `tool_provenance()` now reports
`2026-08-10T01:00:06Z` rather than "unknown". The volume is a deliberate
persistent resource, unlike the images, which are removed.

*Hadolint reads from stdin.* The Dockerfile text is fed to the container rather
than written to a file, so no temporary Dockerfile appears in the working
directory and the text analysed is exactly the one the VCS Connector delivered.
CRLF endings are normalised first, since blob content reflects whatever was
committed.

*Failure detection by output, not exit code.* Hadolint exits non-zero whenever
it reports findings, which is the normal case here, so the exit code alone
cannot signal failure. An empty stdout is what distinguishes a tool that ran
from one that did not.

**Validation against the catalogue.** The component was run over all fifteen
controlled experiments in `experiments/extended_catalog/`, building each pair
through the preparation phase. Four of them carry a recorded `metrics_output.json`:

| experiment | ΔWarnings | ΔInstr | ΔCVEs |
|---|---|---|---|
| experiment_06_R06_InlineStage | +0 = +0 | −3 = −3 | +0 = +0 |
| experiment_09_R09_ExtractRUN | +0 = +0 | +1 = +1 | +0 = +0 |
| experiment_11_R12_RemoveRUNmv | +0 = +0 | −2 = −2 | +0 = +0 |
| experiment_10_R11_MoveStage | +0 = +0 | **−3 vs +1** | +0 = +0 |

Three reproduce the recorded values exactly. The fourth is recorded below.

### Edge Case: Divergence in Experiment R11 (Move Stage)

* **Date:** 2026-08-10
* **Status:** Resolved by design limitation (RF1) — Documented in Section 4.9.
* **Technical Summary:** The R11 refactoring (Move Stage) results in a
  divergence specifically in instruction count (ΔInstr), registering −3 in the
  prototype versus +1 in the global catalog ground truth. The catalog performs
  project-level global accounting across both the original and the newly
  extracted Dockerfile (`Dockerfile.builder`). Conversely, the prototype is
  strictly bound by design requirement RF1 to track a single file path,
  auditing exclusively the primary Dockerfile.
* **Metric Scope Impact:** This scope limitation affects *exclusively* ΔInstr.
  All other metrics for R11 — namely ΔWarnings (Hadolint) and ΔCVEs (Trivy) —
  matched the expected baseline values precisely (`+0 = +0`).
* **Comparative Context:** Refactorings like R09 (Extract RUN) show no
  divergence because they offload logic to shell scripts (which do not count as
  Dockerfile instructions), whereas R11 creates a separate Dockerfile.
* **Decision:** Keep the single-file scope (RF1) as a deliberate architectural
  choice to ensure a strictly deterministic measurement pipeline, avoiding
  fragile heuristics for automatic satellite file aggregation.
* **Action:** This behavior is consciously assumed as a structural property of
  the prototype's scope and is documented in Section 4.9 of the thesis. No code
  modifications are required.

**Testing.** 29 tests in `tests/test_data_extractor.py`. The external tools are
replaced by a fake `subprocess.run` serving recorded Trivy and Hadolint JSON, so
the suite runs without a daemon and without pulling either tool image; one
end-to-end test invokes the real containers against two real images and is
skipped when Docker is unreachable.

- The screen: exactly 47 distinct rules, the default-disabled DL3049–DL3058
  excluded, only screened rules counted, repeated violations of one rule all
  counted, and the PoC-2 criterion of −1 for an eliminated DL3007 (RNF2).
- ΔCVEs: distinct identifiers counted once, per-tier reporting, an unknown
  severity counting in the total but in no tier, and a clean image yielding
  zero rather than an error when Trivy omits the vulnerability list entirely.
- ΔInstr: comments excluded, a backslash-continued instruction counting as one,
  CRLF tolerated, a single added instruction moving the delta by one (RNF2),
  and the source proven free of any Detection Engine import.
- Boundaries: no build or removal command emitted, both images scanned
  read-only, the two scans sharing the database cache volume, and Hadolint
  reading from stdin rather than a path.
- RNF4 contract: a missing docker command, a tool timeout, empty output,
  malformed JSON, an unexpected Trivy shape, an unexpected Hadolint shape,
  non-string Dockerfile content, and parsing failing before any image is
  scanned.
- Deltas: all three signed after minus before, and zero deltas reported as a
  result rather than an absence.

Full suite: **180 passed, 4 skipped** on Windows; **29 passed** for this module
under WSL with the tools reachable, including the end-to-end run.

**Most relevant snippet.**

```python
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            "scan_before": pool.submit(_scan_image, image_before, "before"),
            "scan_after": pool.submit(_scan_image, image_after, "after"),
            "lint_before": pool.submit(_lint_dockerfile, dockerfile_a, "before"),
            "lint_after": pool.submit(_lint_dockerfile, dockerfile_b, "after"),
        }
        outputs, failure = {}, None
        for name, future in futures.items():
            try:
                outputs[name] = future.result()
            except DataExtractorError as exc:
                failure = failure or exc
        if failure is not None:
            raise failure
```

---

## 2026-08-08 — Stage 2 preparation phase: image builder (RNF4)

**Purpose.** Build the two Docker images that Stage 2 consumes, before Stage 2
begins. Owned by the pipeline orchestrator, not by either Stage 2 component.

**Technology.** Docker SDK for Python 7.1.0 (`docker==7.1.0`, added to
`requirements.txt`), validated in Experiment 4.

**Reason for the choice — why the build is a phase and not a component's job.**
Stage 2 runs the Performance Analyzer and the Data Extractor in parallel, and
neither may depend on the other. Both nonetheless need the same resource: the
Performance Analyzer reads the size of each built image, and the Data Extractor
scans those images with Trivy (Table 4.9, step 3b). Leaving the build inside
either component would make the other wait on it, turning a parallel stage into
a sequential one; giving each component its own build would duplicate the most
expensive operation in the pipeline. Lifting the build into a preparation phase
resolves both: the images exist before Stage 2 starts, and the two components
consume them independently and concurrently.

**Key design decisions.**

*References, not objects.* `BuiltImagePair` carries image IDs as strings, not
SDK objects. The Stage 2 components each open their own Docker connection and
look the images up by ID, so they share no client, no connection and no object
graph with this phase or with each other. The only thing crossing the boundary
is an identifier, consumed read-only on both sides — which is what makes their
independence structural rather than a matter of convention.

*In-memory build context.* The build context is assembled as a tar archive in
`io.BytesIO` and handed to the daemon as a byte stream (`custom_context=True`),
never as a directory path. Two properties follow. First, analysing a repository
writes nothing to the caller's working directory — no temporary Dockerfile, no
context copy. Second, the Dockerfile is *injected* into the archive rather than
read from disk, so the content delivered by the VCS Connector is built exactly
as it was committed. A file already named `Dockerfile` at the root of the
context is skipped, since the state under analysis supersedes it.

The archive also solves a problem an empty context would have created: passing
only `fileobj` gives the build no context at all, so every Dockerfile carrying
a COPY — which is most of the catalogue — would fail. The optional
`context_path` argument lets the caller supply the directory whose files
accompany both builds, and `.git`, `__pycache__`, `.venv` and `node_modules`
are excluded from it.

*Guaranteed cleanup.* Both images are removed when the preparation context
closes, in a `finally` block that covers all three failure shapes: a second
build that fails after the first succeeded, an exception raised by either Stage
2 component inside the block, and an ordinary return. Without this a
catalogue-wide run would leave dozens of images behind and exhaust the daemon's
storage. Removal errors are swallowed deliberately, because an exception raised
during cleanup would mask the failure that triggered it.

*`pull=False`.* The base image is not re-pulled, so both states build against
the same locally cached base. This is what keeps the two measurements
comparable: a tag that moved upstream between the two builds would otherwise
contaminate the delta with a change that is not the refactoring's.

*`docker_engine_version()`.* RNF5 requires the report to record the version of
every external tool invoked, including the Docker Engine. The preparation phase
is where the Docker environment is established, so it is where that version is
read and handed to the Report Generator.

*A distinct exception type.* Preparation failures raise `ImageBuildError`, not
the `PerformanceAnalyzerError` of the measurement component. RNF4 asks for
distinct informative exceptions, and the two failures are genuinely different
events: a build that does not complete aborts the analysis before Stage 2, and
a size that cannot be inspected fails one metric of a stage already running.

**Testing.** 18 tests in `tests/test_image_builder.py`, running against a fake
Docker client so the suite needs no daemon; one end-to-end test builds two real
Alpine images and is skipped when Docker is unreachable.

- Building: both references yielded, identifiers rather than SDK objects, the
  context sent as an in-memory stream and never as a path, lower-case tags, and
  the Engine version reported for RNF5.
- Cleanup: both images removed when the context closes and still present while
  it is open, the first removed when the second build fails, both removed when
  a Stage 2 component raises, and a failing removal not masking the original
  error.
- RNF4 contract: unreachable daemon, build failure naming the offending state,
  API error, and a context path that is not a directory.
- Context assembly: the Dockerfile content travels intact, context files and
  subdirectories are included, a `Dockerfile` in the context is superseded,
  `.git` is excluded, and building writes nothing to the working directory.

**Most relevant snippet.**

```python
    client = _connect()
    built: List[Image] = []
    try:
        image_before = _build_image(client, dockerfile_before, resolved_context, "before")
        built.append(image_before)
        image_after = _build_image(client, dockerfile_after, resolved_context, "after")
        built.append(image_after)

        yield BuiltImagePair(image_before=image_before.id, image_after=image_after.id)
    finally:
        _remove_images(client, built)
```

---

## 2026-08-08 — Performance Analyzer (RF4, RNF1, RNF4)

**Purpose.** Stage 2 component, running in parallel with the Data Extractor. It
receives the references to the two images the preparation phase built and
returns the signed size delta between them.

**Technology.** Docker SDK for Python 7.1.0, validated in Experiment 4. Size is
read from `image.attrs["Size"]` — the VirtualSize, the total uncompressed byte
count of all image layers, as a 64-bit integer.

**Reason for the choice.** The Docker CLI was rejected at design time: it
applies decimal rounding and human-readable truncation by design (Docker issue
#31298), which would collapse the micro-variations the catalogue produces —
the +417 bytes of R09 — to zero and violate RNF1. The SDK queries the daemon
API endpoint directly and returns the raw integer.

**Key design decisions.**

*The component measures and nothing else.* It does not build, does not remove,
and never reads a value produced by the Data Extractor: ΔSize is computed from
the two images alone, just as ΔCVEs, ΔWarnings and ΔInstr are computed without
ΔSize. That mutual independence is what allows the two Stage 2 components to
run concurrently. The module holds no state and opens its own Docker
connection rather than receiving one, so it shares no mutable object with its
sibling.

*The delta is expressed in bytes alone.* `SizeMetric` carries `size_before`,
`size_after` and `delta_size`, all in bytes. The sign convention is the study's:
`size_after - size_before`, so a negative delta is a size reduction. Measuring
in bytes alone is what keeps the four metrics uniform: ΔCVEs, ΔWarnings and
ΔInstr are absolute signed counts, so a relative figure on this one would hand
the Report Generator a metric in a different form from its three siblings. A
percentage remains derivable from the two absolute sizes by whoever needs it,
without the component committing the pipeline to it.

**Problems and solutions — image size is not bit-for-bit reproducible.**
Measuring the R09 catalogue pair repeatedly returned deltas of +414, +416,
+417, +418 and +419 bytes across runs, against the +417 recorded in
`experiments/extended_catalog/experiment_09_R09_ExtractRUN/`. The cause is not
the component: four consecutive `DOCKER_BUILDKIT=0 docker build --no-cache`
runs through the Docker CLI — the experiment's own command, with no code of
this prototype involved — produced

| run | before | after | delta |
|---|---|---|---|
| 1 | 3,633,776 | 3,634,193 | +417 |
| 2 | 3,633,775 | 3,634,191 | +416 |
| 3 | 3,633,776 | 3,634,192 | +416 |
| 4 | 3,633,774 | 3,634,193 | +419 |
| recorded | 3,633,775 | 3,634,192 | +417 |

Each absolute size varies within a band of about 2 bytes and the delta within
about 3, and the recorded values sit inside those bands. Docker Engine 29.1.3
on WSL2 therefore does not produce a byte-identical image from byte-identical
inputs. A trivially simple Dockerfile does reproduce exactly; the variation
appears with builds that copy from a context and write files in a RUN layer.

Three consequences follow, none of which the component can remove:

1. The design chapter states that image size is "a deterministic function of
   the Dockerfile content and the base image state, producing the same byte
   count for the same inputs every time". At byte resolution that is not what
   this environment does, and the sentence overstates the guarantee.
2. RNF1's byte-level precision is a property of the *retrieval* method, and it
   holds: the SDK returns exact integers where the CLI would round. What does
   not hold is byte-level *reproducibility* of the measured object. The two are
   distinct claims and only the first belongs to the Performance Analyzer.
3. Deltas whose magnitude is within the noise band cannot be distinguished from
   it. R09's +417 is two orders of magnitude above the band and stands
   unaffected. R08's recorded +1 byte does not exceed it — the chapter already
   classifies that result as neutral and "far below the relevance threshold",
   so its interpretation is unchanged, but the figure should be read as
   indistinguishable from zero rather than as a measured increase.

No experiment file was altered. The recorded values remain valid single-run
observations of the quantity they measure.

**Testing.** 15 tests in `tests/test_performance_analyzer.py`, running against
a fake Docker client so the suite needs no daemon; one end-to-end test builds
two real images through the preparation phase and is skipped when Docker is
unreachable.

- RF4/RNF1 computation: the PoC-3 reference delta (29,748,045 → 3,429,495 =
  −26,318,550 bytes), the +417 byte micro-variation of R09 surviving intact,
  the signed convention in all three directions, a zero before size, and the
  metric carrying byte fields only.
- Stage 2 boundaries: exactly the two given images are inspected, the fake
  client asserts on any build call so the component provably never builds, and
  both images are left in place for the Data Extractor running alongside.
- RNF4 contract: unreachable daemon, an unknown image naming the offending
  state, API error, missing `Size` attribute, and a non-integer size (what the
  rejected CLI path would deliver).

Full suite: **152 passed, 3 skipped** on Windows; **33 passed** for both Stage 2
modules under WSL with the daemon reachable, including the end-to-end builds.

**Most relevant snippet.**

```python
    client = _connect()
    try:
        return SizeMetric.from_sizes(
            _image_size(client, image_before, "before"),
            _image_size(client, image_after, "after"),
        )
    finally:
        with contextlib.suppress(Exception):
            client.close()
```

---

## 2026-08-08 — Detection Engine: R09 (Extract RUN Instructions) — 14 of 14 rules

**Purpose.** Detect a complex inline shell sequence taken out of a RUN into an
external script, which the Dockerfile then copies in and executes, leaving a
single call in place of the chained commands. This is the fourteenth and last
rule of the catalogue, completing RF2.

**Technology.** dockerfile-parse 2.0.1 (unchanged). Reuses `_shell_segments`
(introduced for R01) and `_transfer_operands` (introduced for R12).

**Key design decisions.** The script is a file outside the Dockerfile that the
pipeline never sees, since the VCS Connector delivers one Dockerfile at two
commits. As with Move Stage (R11), the refactoring is still decidable from the
Dockerfile alone, because moving work into a script leaves three facts in it:

1. a COPY or ADD that did not exist before brings a shell script into the
   image, so a new external artefact arrived;
2. a RUN executes that script, tying the artefact to the build instead of
   leaving it as an unused file;
3. the total number of shell command segments across the RUN instructions
   falls, showing the commands left the Dockerfile rather than being written
   into the script for the first time.

The third condition carries the directional weight and separates the
refactoring from simply adding new functionality through a script: without
shell work leaving the file, nothing was extracted. It also makes the reverse
path silent, since inlining a script back makes the COPY disappear rather than
appear.

Only `.sh` and `.bash` sources qualify as scripts. A RUN body is what gets
extracted, so the carrier of the extracted work is a shell script; admitting
arbitrary transferred files would let any new COPY paired with an unrelated RUN
reduction satisfy the rule.

**Problems and solutions.** Two false positives surfaced on the R12 mock pair,
where `COPY entrypoint.sh /tmp/entrypoint.sh` becomes
`COPY entrypoint.sh /app/bin/entrypoint.sh` and the RUN mv instructions
disappear. Both were real defects in the rule, not artefacts of that pair:

- *Path mention read as execution.* The first version matched the script name
  anywhere in the RUN body, so `RUN chmod +x /app/bin/entrypoint.sh` counted as
  an invocation. Fixed by requiring the script to stand where a command stands:
  as a segment's own command (`/app/setup.sh`, `./setup.sh`) or as the file an
  interpreter is handed (`sh setup.sh`). A path passed to another command
  prepares the script but does not run it.
- *Relocation read as arrival.* The check for a new script compared the whole
  COPY argument string, so a script already in the image whose destination
  changed looked new. Fixed by comparing the script file names the two states
  deliver, which is what identifies the artefact regardless of where it lands.

Both fixes made the rule stricter on its own terms and are covered by dedicated
regression tests, so the R12 pair reports `['R12']` alone again.

**Testing.** 9 tests: mock pair mirroring the catalogue experiment, CRLF
variant, a directory destination combined with an `sh setup.sh` invocation, a
noise variant with an unrelated WORKDIR edit, and five negatives — the script
never executed (only chmod'd), the script merely relocated, no shell work
leaving the file, a non-script file copied in, and the reverse path of inlining
the script back. 121 tests pass, 1 skipped.

The engine was also run over every controlled pair in
`experiments/extended_catalog/`, each of which reports exactly the rule its
folder is named for: R01, R02, R03, R04, R05, R06, R07, R08, R09, R12, R13
(twice) and R14 (twice) in isolation, and `['R10', 'R11']` for the Move Stage
pair, the composite detection accepted by the author on 2026-08-08.

**Most relevant snippet.**

```python
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
```

---

## 2026-08-08 — Detection Engine: R11 (Move Stage)

**Purpose.** Detect a stage taken out of the Dockerfile into a standalone file
of its own, built separately, with the main file keeping only a reference to
the image that build produces.

**Technology.** dockerfile-parse 2.0.1 (unchanged). Built on the stage analysis
base introduced with R06.

**Key design decisions.** The extracted Dockerfile is a second file the pipeline
never sees, since the VCS Connector delivers one Dockerfile at two commits. The
refactoring is nonetheless detectable from the main file alone, because it
leaves a precise signature there: the stage stays in place and stays consumed,
while its body moves out and its FROM starts naming an externally built image.
Three facts establish it:

1. the stage had a body in the before state and has none in the after state,
   so its work left the file;
2. its FROM reference changed — an emptied stage still on the same base would
   be a deletion, not a move;
3. something still reads from it, so the build continues to consume what the
   stage delivers.

The stage count is unchanged, which is exactly what separates this refactoring
from Extract Stage (R05) and Inline Stage (R06) and keeps the three stage rules
from competing for the same pair. Reported are the instructions that left the
file (before) and the emptied FROM now naming the external image (after).

**Observation for validation: R10 co-fires on this pair.** Moving the stage out
changes the FROM of the builder stage from `alpine:3.20` to `r11-builder:1.0`
with the alias preserved, which structurally satisfies the entity-substitution
criterion of R10 (Update Base Image). Running the catalogue pair reports
`['R10', 'R11']`. Both are structurally true and the non-exclusion principle
admits both, but R10 is arguably a semantic false positive here: the developer
did not update a base image, they moved a stage out and the reference change is
a consequence of that single event. Left as is pending the author's decision,
since suppressing it would couple R10 to R11's logic and the rules are
deliberately independent (RNF3).

**Problems and solutions.** `_stages` strips the opening FROM from each stage
body, so the instruction to report as the after state had to be recovered from
the instruction list. Collecting the FROM instructions of the after state in
order and indexing them by the stage index works because `_stages` assigns
indices in the same order.

**Testing.** 6 tests: mock pair mirroring the catalogue experiment, CRLF
variant, an assertion that neither R05 nor R06 fires (the stage count is
unchanged), and three negatives — a body merely deleted while the base stays
the same, an emptied stage nothing consumes, and the reverse path of bringing
the body back. Assertions use membership rather than equality because of the
R10 co-firing described above. 112 tests pass, 1 skipped.

**Most relevant snippet.**

```python
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
```

---

## 2026-08-08 — Detection Engine: R05 (Extract Stage)

**Purpose.** Detect the split of a single-stage build into a multi-stage one,
where the build environment stays behind and the final image receives only what
a `COPY --from` brings across.

**Technology.** dockerfile-parse 2.0.1 (unchanged). Built on the stage analysis
base introduced with R06.

**Key design decisions.** R05 is the exact inverse of R06 and reuses the same
reasoning. A rising stage count is not evidence on its own, since a stage may
simply be added to do new work, so the rule requires positive evidence that an
existing build was split:

1. the new stage is read from by a `COPY --from` in the after state;
2. nothing read from that stage in the before state, so it is genuinely new
   rather than pre-existing;
3. at least one of its instructions was already present in the before state,
   showing the work moved into the stage instead of being written there for the
   first time.

Condition 3 is what separates extraction from addition: a stage added to do
work that never existed before is not a refactoring of the existing build.
Reported are the instructions that moved into the new stage (before) and the
`COPY --from` that now consumes it (after) — the mirror image of what R06
reports. The two rules are mutually exclusive by construction, since one
requires the stage count to rise and the other to fall.

**Problems and solutions.** Adding R05 broke the R06 test that asserted the
reverse path produced an empty result: with both rules present, running the R06
pair backwards is a genuine extraction and now reports R05. The assertion was
narrowed from "no detection at all" to "R06 is not among the detections", which
is what the test actually meant. The same narrowing was applied to the new R05
reverse-path test. This is the non-exclusion principle showing up in the test
suite: a pair can legitimately match a different rule in each direction.

**Testing.** 5 tests: mock pair mirroring the catalogue experiment (Rust build
split with an alpine runtime), CRLF variant, and three negatives — a new stage
doing work that did not exist before, a stage nothing reads from, and the
reverse path. The rule was additionally run against the real pair in
`experiments/extended_catalog/experiment_05_R05_ExtractStage_Security`, where it
reports the four extracted build instructions and the `COPY --from=builder`;
running that pair in both directions yields R05 one way and R06 the other. 106
tests pass, 1 skipped.

**Most relevant snippet.**

```python
    for stage in stages_b:
        consumers = [e for e in instructions_b
                     if _stage_reference_of(e) == stage.identity]
        if not consumers:
            continue  # nothing reads from it: not the extracted stage
        if stage.identity in references_before:
            continue  # already consumed before: the stage is not new
        moved = [e for e in stage.instructions if body_before[e] > 0]
        if not moved:
            continue  # its work is new, not extracted from the previous build
```

---

## 2026-08-08 — Detection Engine: stage analysis base + R06 (Inline Stage)

**Purpose.** Introduce the stage decomposition that every stage-level rule needs
(R05, R06, R09, R11) and implement the first of them, R06, which merges a stage
that provides no benefit into the one that consumed it.

**Technology.** dockerfile-parse 2.0.1 (unchanged).

**Stage analysis base.** `_stages()` decomposes an instruction list into `Stage`
records carrying the stage index, the image reference, the alias, and the
instructions of its body with the opening FROM excluded. A `Stage.identity`
property returns how a `COPY --from` names the stage — its alias when it has
one, otherwise its index — so both `--from=builder` and `--from=0` resolve
through the same path. Instructions appearing before the first FROM belong to no
stage and are skipped, since they are not part of any stage body.
`_stage_reference_of()` reads the `--from=` target of a COPY or ADD. These three
pieces are the shared foundation for the remaining stage rules.

**R06 design decisions.** A falling stage count is not evidence on its own,
because a stage can also be plainly deleted. Following the same fusion-proof
reasoning adopted for R01, the rule requires positive evidence that the stage
was absorbed rather than removed, through three facts:

1. the stage was read from by a `COPY --from` in the before state;
2. no instruction reads from it any more in the after state;
3. at least one instruction of that stage is present in the surviving stages,
   showing its work moved rather than vanished.

Condition 3 is deliberately a floor rather than full preservation, consistent
with the fusion-proof criterion: developers routinely adjust an instruction
while inlining, and requiring every instruction to survive verbatim would miss
those commits. What is reported is the `COPY --from` that consumed the stage
(before) and the instructions absorbed into the surviving stage (after).
Splitting one stage into two is the reverse path and is never reported.

**Problems and solutions.** Identifying "the stage that disappeared" by
comparing aliases fails for unnamed stages, which have no alias and are referred
to by index — and the index of a surviving stage shifts once an earlier stage is
removed. Keying on the consumption relation instead (which stage a `COPY --from`
read from, and whether anything still reads from it) sidesteps the renumbering
entirely and handles named and unnamed stages with one code path.

**Testing.** 6 tests: mock pair mirroring the catalogue experiment, CRLF
variant, an unnamed stage referenced by index (`--from=0`), and three negatives
— the stage's work vanishing without absorption, a stage still consumed after
the change, and the reverse path of extracting a stage. The rule was
additionally run against the real pair in
`experiments/extended_catalog/experiment_06_R06_InlineStage`, where it reports
the removed `COPY --from=builder` and the three absorbed instructions. 101 tests
pass, 1 skipped.

**Most relevant snippet.**

```python
    for stage in stages_a:
        consumers = [e for e in instructions_a
                     if _stage_reference_of(e) == stage.identity]
        if not consumers:
            continue  # nothing consumed this stage: not the inlined one
        if stage.identity in references_after:
            continue  # still read from: the stage survives
        absorbed = [e for e in stage.instructions if body_after[e] > 0]
        if not absorbed:
            continue  # its work vanished: a deletion, not an inlining
```

---

## 2026-08-08 — Detection Engine: R07 (Sort Instructions)

**Purpose.** Detect the rearrangement of instructions that preserves cache
validity across rebuilds, by placing stable and resource-intensive steps before
frequently modified ones.

**Technology.** dockerfile-parse 2.0.1 (unchanged).

**Key design decisions.** Two conditions establish that the change is a pure
rearrangement: the multiset of instructions is identical, so nothing was added,
removed or edited, and the sequence differs.

Direction was decided by the author (2026-08-08) after being presented with the
alternatives: the rule is **directional with a mechanical proxy**, rather than
reporting any reordering. The catalogue states the mechanism as "postponing
frequently modified instructions and prioritising stable, resource-intensive
steps", but "stable" and "frequently modified" are not readable from a single
file pair, so the proxy the refactoring itself implies is used: a RUN that
installs dependencies is the stable, expensive step, and a COPY or ADD of
project files is what changes on almost every commit. Instructions that are
neither carry no ordering signal and are ignored.

The direction is then measured as a count of **cache inversions**: volatile
transfers standing before dependency installations, each of which invalidates an
expensive layer whenever a source file changes. The rearrangement qualifies only
when that count falls. Moving a COPY ahead of an installation raises it, which
is technical debt rather than a refactoring, and yields an empty result.

Only the instructions that actually changed position are reported, so a FROM
that stayed in place does not appear in the result.

**Problems and solutions.** A reordering with no cache effect — swapping two
COPY instructions between themselves — satisfies both structural conditions and
would be reported by a purely structural rule. The inversion count resolves it
without a special case: the count is equal on both sides, the strict decrease
fails, and nothing is reported.

**Testing.** 6 tests: mock pair mirroring the catalogue experiment (installs
moved ahead of transfers), CRLF variant, and four negatives — the cache-worsening
reverse path, a commit that also edits an instruction, a reordering between two
volatile transfers, and an unchanged order. The rule was additionally run against
the real pair in `experiments/extended_catalog/experiment_07_R07_SortInstructions_Security`,
where the inversion count falls from 3 to 0 and R07 is reported, while the
reverse direction yields an empty result. 95 tests pass, 1 skipped.

**Known limitation.** The rule requires the instruction multiset to be identical,
so a commit that rearranges instructions *and* edits one of them is not
reported. This is the strict reading; it may be revisited in the same way the
fusion-proof criterion relaxed R01, should real-world commits justify it.

**Most relevant snippet.**

```python
def _cache_inversions(instructions: list) -> int:
    """Count volatile steps standing before stable ones."""
    classes = [c for c in (_cache_class(e) for e in instructions) if c]
    return sum(
        1
        for index, current in enumerate(classes)
        if current == "volatile"
        for later in classes[index + 1:]
        if later == "stable"
    )
```

---

## 2026-08-07 — Detection Engine: R13 (Update RUN Instruction)

**Purpose.** Detect the reformatting of a RUN instruction: splitting it across
lines with backslashes and sorting its arguments alphanumerically, both
recommended by the Docker Documentation and cited in the catalogue entry.

**Technology.** dockerfile-parse 2.0.1 (unchanged).

**Key design decisions.** The catalogue entry states that "the package set and
its versions are identical in both states", which gives the mechanical
criterion directly: the instruction text changed while the commands and
arguments it carries did not. RUN instructions are aligned by position and a
pair is reported when the raw values differ but the multiset of
whitespace-separated tokens is equal.

The multiset covers both components of the refactoring in one comparison:

- **reordering** keeps the same tokens in a different sequence;
- **line splitting** keeps the same tokens with different spacing, because
  backslash continuations resolve into the argument string and leave the
  indentation of the physical lines inside it.

Any change to the token multiset — a package added, removed, or re-versioned —
is a content edit and is not reported. When the number of RUN instructions
differs the change belongs to consolidation or removal (R01, R12) and the rule
stays silent, so the three RUN-level rules do not compete for the same pair.

**Problems and solutions.** Comparing normalised strings would have collapsed
the line-splitting case: normalising whitespace makes a purely reformatted RUN
identical to its original, and the rule would never fire on it. Comparing the
raw values for inequality and the token multisets for equality keeps both cases
detectable with a single condition.

**Testing.** 7 tests: mock pair mirroring the catalogue experiment (split plus
alphanumeric sort), line splitting with no reordering, CRLF variant,
WORKDIR/CMD noise, and three negatives — a package added, a version changed,
and a changed RUN count. The rule was additionally run against both real pairs
in the catalogue, `experiment_12_R13_UpdateRUN_Performance` (alpine) and
`experiment_13_R13_UpdateRUN_Security` (debian), reporting R13 on each. 89
tests pass, 1 skipped.

**Most relevant snippet.**

```python
    for before, after in zip(runs_a, runs_b):
        if before == after:
            continue
        if Counter(before.split()) == Counter(after.split()):
            changed_before.append(Instruction("RUN", before))
            changed_after.append(Instruction("RUN", after))
```

---

## 2026-08-07 — Detection Engine: R12 (Remove RUN Instruction, mv command)

**Purpose.** Detect the elimination of a RUN whose sole purpose is to move a
file, where the destination path is set directly in the preceding COPY or ADD.

**Technology.** dockerfile-parse 2.0.1 (unchanged).

**Key design decisions.** A RUN disappearing is not evidence on its own: that
alone is a deletion. The relocation has to be shown to have migrated into the
transfer instruction, so three facts must hold together before the rule fires:

1. the RUN does nothing but move files. `mkdir` is tolerated as a companion,
   because it only prepares the directory the move lands in and COPY creates
   that directory by itself — this is exactly the shape of the catalogue
   experiment (`RUN mkdir -p /app/config && mv /tmp/app.conf /app/config/app.conf`);
2. in the before state a COPY or ADD landed on the path the move read from,
   typically a temporary location;
3. in the after state a COPY or ADD carrying the **same sources** lands
   directly on the path the move wrote to.

`_move_relocations` returns None whenever the RUN does anything beyond moving,
and also for multi-source `mv`, which is not a single relocation.
`_transfer_operands` skips `--from` and `--chown` flags and takes the last
operand as the destination, per Dockerfile syntax. Adding a `RUN mv` is the
reverse path and is never reported.

**Problems and solutions.** Matching only on "a RUN with mv disappeared" reports
a dropped relocation as a refactoring. Requiring the destination to reappear in
a transfer instruction with the same sources resolves it: in the pair
`COPY app.txt /tmp/app.txt` + `RUN mv /tmp/app.txt /opt/app.txt` → `COPY app.txt
/tmp/app.txt`, the COPY still lands on the temporary path, no transfer carries
the move's destination, and the rule stays silent.

**Testing.** 7 tests: mock pair mirroring the catalogue experiment (two RUN mv
removed, two COPYs landing directly), CRLF variant, bare `mv` without `mkdir`,
WORKDIR/CMD noise, and three negatives — a RUN that also runs `chmod`, a
relocation dropped without moving into the COPY, and the reverse path. The rule
was additionally run against the real pair in
`experiments/extended_catalog/experiment_11_R12_RemoveRUNmv`, where it reported
both removed RUNs and both direct COPYs. 82 tests pass, 1 skipped.

**Most relevant snippet.**

```python
        for source, destination in relocations:
            # the transfer that used to land on the path the move read from
            origin = next(
                (e for e in transfers_a
                 if (ops := _transfer_operands(e.value)) and ops[1] == source), None)
            if origin is None:
                continue
            origin_sources = _transfer_operands(origin.value)[0]
            # the same sources now landing straight on the move's destination
            landed = next(
                (e for e in transfers_b
                 if (ops := _transfer_operands(e.value))
                 and ops[1] == destination and ops[0] == origin_sources), None)
```

---

## 2026-08-07 — Conformance alignment with the revised design + R01 (Inline RUN Instructions)

**Purpose.** Audit the existing code against the revised `DESIGN_CHAPTER.md` and
`PROJECT_CONTEXT.md`, close the gaps found, and implement R01 — the rule whose
detection is the acceptance criterion of RF2.

**Technology.** dockerfile-parse 2.0.1, Python 3.14.6 (unchanged).

**Audit result.** The VCS Connector satisfies RF1, RNF4 and RNF5 as written and
needed no change. The Detection Engine showed three divergences, all fixed in
this pass:

1. **RF3 naming.** The chapter specifies a typed `DetectionResult`; the code
   named the type `Detection`. Renamed, with the docstring now stating why no
   impact field exists: the identifier is a label, and the deltas are computed
   independently downstream.
2. **RNF4 gap.** `parse_instructions` had no error handling, so malformed
   content propagated the raw library exception. Added `DockerfileParseError`,
   raised both for non-text input and for any parser failure, so the pipeline
   can tell malformed content apart from a build or daemon failure.
3. **RF2 unmet.** Its acceptance criterion is the 4-to-1 RUN consolidation of
   Experiment 5, which requires R01 — not implemented until now.

**R01 design decisions.**
- Granular and directional over the RUN subset: the count of RUN instructions
  must fall. Splitting one RUN into several is the reverse path and yields an
  empty result.
- **Content preservation check** (third challenge of the design chapter): a
  falling RUN count alone is ambiguous between consolidation and deletion. The
  commands of the disappearing instructions are looked for inside the surviving
  ones by splitting RUN bodies on the shell operators `&&`, `||` and `;` and
  comparing the resulting command multisets. Every command accounted for means
  consolidation; any command missing means deletion, and nothing is reported.
- Whitespace inside segments is normalised, because a multi-line RUN joined by
  backslash continuations keeps the indentation of the physical lines inside
  its argument string.
- The instructions reported are those that did not survive verbatim on their
  side of the pair, so a partial consolidation reports only the RUNs that were
  actually merged and leaves untouched ones out.
- Registered first in the rule registry, so the registry index follows the
  catalogue numbering.

**Problems and solutions.** The naive check "did the RUN count fall?" reports a
deletion as a refactoring. The segment multiset comparison resolves it: in the
pair `RUN a / RUN b / RUN c` → `RUN a && b`, the segment `echo c` is absent from
the after state, the difference is non-empty, and the rule stays silent.

**Testing.** 7 tests for R01: the 4-to-1 mock pair mirroring Experiment 5 (RF2
acceptance criterion, asserting 4 instructions before and 1 after), a CRLF
variant, WORKDIR/CMD noise, partial consolidation reporting only the merged
RUNs, and three negatives — deletion, splitting, and unchanged RUN count. Plus
2 tests for the RNF4 exception. 73 tests pass, 1 skipped (the
docker/getting-started integration, which needs a local clone).

**Most relevant snippet.**

```python
    # Directional: consolidation reduces the number of RUN instructions.
    if not runs_a or len(runs_a) <= len(runs_b):
        return None

    # Content preservation: every command of the before state must survive.
    segments_before = Counter(seg for value in runs_a for seg in _shell_segments(value))
    segments_after = Counter(seg for value in runs_b for seg in _shell_segments(value))
    if segments_before - segments_after:
        return None  # commands disappeared: deletion, not consolidation
```

**Revision, same day — permissive content preservation for R01 (author's
decision).** The first implementation rejected any pair where a command
disappeared, treating it as a deletion. Real commits routinely combine inlining
with cleanup, dropping an adjacent command in the same change, and the strict
rule missed those. The check was therefore inverted: instead of requiring every
command to survive, it looks for positive evidence of merging. Each command is
traced back to the RUN instruction that held it, and a surviving RUN counts as a
merge when its commands come from two or more previous RUNs. Disappearing
commands are tolerated; the absence of merging is not, so a plain deletion still
yields an empty result. Only the RUNs actually merged are reported, so a dropped
instruction does not enter the result. Behaviour after the change:

| Pair | Reported |
|---|---|
| `RUN a / RUN b / RUN c` → `RUN a && b` (c dropped) | R01 — inlining mixed with cleanup |
| `RUN a / RUN b / RUN c` → `RUN a` | none — plain deletion |
| `RUN a / RUN b` → `RUN b` | none — instruction merely dropped |
| 4 RUNs → 1 (Experiment 5) | R01 — unchanged |
| `RUN a && b` → `RUN a / RUN b` | none — reverse path, unchanged |

Two tests were replaced by three: the former deletion negative became a positive
for the mixed case, and two negatives now cover plain deletion. 75 tests pass.

⚠️ **Chapter divergence to resolve.** Section 4.1.3 (third challenge) and
`PROJECT_CONTEXT.md` still state that a change whose commands "disappeared
without trace" is classified as a deletion and not reported. The code no longer
enforces that strictly. The text has to be updated to describe the evidence-of-
merging criterion actually implemented.

**Pending, recorded for the Report Generator.** RF7 lists the delta keys as
`delta_size, delta_warnings, delta_hadolint, delta_logical_instructions`, which
duplicates the warning key and omits the CVE one. Confirmed with the author: the
code will emit `delta_size`, `delta_cves`, `delta_warnings` and
`delta_logical_instructions`; the chapter text is corrected separately.

---

## 2026-07-06 — Detection Engine: R14 (Rename Image)

**Purpose.** Detect stage-naming refactorings in multi-stage builds. The
symmetry ambiguity flagged in the author's architecture directive was
resolved by the author with an explicit validation logic before any code
was written.

**Key design decisions.**
- **Validation logic (author's specification, 2026-07-06).** On FROMs whose
  image reference is untouched (identical name, tag, digest, and platform
  flags — otherwise the change belongs to R02/R10):
  - *Accepted — alias appears* (`alias_before IS NULL AND alias_after IS
    NOT NULL`, e.g. `FROM golang:1.22` → `FROM golang:1.22 AS build`):
    eliminates the technical debt of numeric stage references (`--from=0`).
  - *Accepted — alias changes* (both non-null, different, e.g. `AS build` →
    `AS builder`): direct syntactic equivalence with DRMiner's Rename Image.
  - *Excluded — alias disappears* (non-null → null): reverse path,
    reintroduces numeric-reference debt; ignored by design.
- **FROM-only scope (author's decision).** Consequential updates to
  `--from=` references elsewhere are tolerated noise, not verified or
  reported — the rule stays surgical over the FROM subset.
- Alignment by stage position, counts must match (otherwise silent), as in
  R02/R10. The three FROM rules are mutually exclusive per FROM by
  construction: R02 = same name, tag changed; R10 = name changed; R14 =
  image untouched, alias mutated. A FROM mixing image and alias changes
  matches none of them.

**Testing.** Positives: naming an unnamed stage (mock pair with the numeric
`--from=0` reference updated to `--from=build` as tolerated noise), alias
rename, CRLF variant, WORKDIR/RUN noise, and combined `[R02, R14]` (one
stage gains an alias while another gets a tag bump). Negatives: alias
disappearing (reverse path) and alias mutation combined with an image change
(neither R14 nor R02). 56 detection tests; 64 passing overall with the VCS
Connector suite.

---

## 2026-07-06 — Detection Engine: R10 (Update Base Image)

**Purpose.** Detect the substitution of the base-image entity — the exact
complement of R02's entity-preservation condition. Implemented after the
author decided the direction question presented beforehand.

**Key design decisions.**
- **Direction (author's decision, Option A, 2026-07-06).** The catalogue
  direction — "towards a lighter and more secure alternative" — is empirical
  by nature (ΔSize, ΔCVEs) and cannot be decided by static text comparison
  without inventing knowledge (a curated "minimal image" list was rejected)
  or inverting the fixed pipeline order (metric-gated detection was
  rejected). The rule therefore reports the structural operation for ANY
  entity substitution, including the reverse direction; the direction is
  judged downstream by the Performance Analyzer / Data Extractor
  measurements and the RF6 trade-off flag. Documented exception to the
  static directional law.
- Mechanics: FROMs aligned by stage position (counts must match, otherwise
  silent — Extract/Inline Stage territory); a FROM is R10 when the
  repository name differs while platform flags and stage alias are
  preserved; tag and digest may change freely as part of the new reference.
  Mutually exclusive with R02 per FROM by construction (name equal vs name
  different).
- Entity comparison is textual: `ubuntu` vs `library/ubuntu` vs
  `docker.io/library/ubuntu` are the same image for Docker but different
  strings for the rule — documented limitation (conservative: such a change
  reports R10 rather than being normalised away).
- Fossil cleanup in the same pass: three R02-era tests asserting empty
  results for name changes now assert the legitimate `R10` detection
  (`...defers_full_substitution_to_r10`, registry-port case, and the
  multi-stage case, which now yields `[R02, R10]`).

**Testing.** Positives: mock pair mirroring PoC-3 (`ubuntu:22.04` →
`alpine:3.19`), CRLF variant, WORKDIR/RUN noise, reverse substitution
(alpine→ubuntu, direction judged by metrics), and combined `[R03, R10]`
(non-exclusion, registry order). Negatives: alias changed together with the
entity (not a clean R10), and stage count differing (ambiguous alignment).
49 detection tests; 57 passing overall with the VCS Connector suite.

---

## 2026-07-06 — Detection Engine: R04 (Add ARG Instruction)

**Purpose.** Structural twin of R03, implemented on the author's explicit
go-ahead under the standard workflow.

**Key design decisions.**
- Detection is by identifier: the rule reports every ARG instruction in the
  after version whose identifier (`NAME[=default]` — the part before the
  first `=`) is absent from the ARG declarations of the before version.
  `ARG NAME` without a default declares the identifier just the same.
- Directional: changing only the default value of an existing identifier is
  a modification, and removing an ARG is the reverse path — both yield an
  empty result.
- `instructions_before` is empty in the Detection, as with R03.

**Testing.** Positives: minimal mock pair (`ARG APP_VERSION=1.0` before the
FROM), ARG without default, CRLF variant, WORKDIR/CMD noise, and combined
`[R03, R04]` (one commit adding an ENV and an ARG, non-exclusion in registry
order). Negatives: ARG removal (reverse path) and default-value-only update.
42 detection tests; 50 passing overall with the VCS Connector suite.

---

## 2026-07-06 — Detection Engine: R03 (Add ENV Variable)

**Purpose.** Next easiest rule of the extended catalogue, implemented on the
author's explicit go-ahead under the standard workflow (directional
mechanical logic → full test suite → 100% green → log).

**Key design decisions.**
- Detection is by variable NAME, the mechanical criterion that separates an
  addition from a modification: the rule reports every ENV instruction in
  the after version declaring at least one name absent from the before
  version's ENV declarations. Both syntaxes handled: `ENV A=1 B=2`
  (`key=value` pairs, possibly several per instruction) and the legacy
  space-separated single-variable form `ENV MODE dev`.
- Directional: changing the value of an existing name is a modification and
  removing an ENV is the reverse path — both yield an empty result.
- A new name appended to an existing multi-variable ENV (`ENV A=1` →
  `ENV A=1 B=2`) counts as an addition: the instruction now declares a name
  that did not exist before.
- `instructions_before` is empty in the Detection: an addition has no
  counterpart instruction in version A.

**Testing.** Positives: minimal mock pair, CRLF variant, WORKDIR/RUN noise,
new name in multi-variable ENV, legacy form, and combined `[R02, R03]`
(tag pin + new ENV, non-exclusion in registry order). Negatives: ENV
removal (reverse path) and value-only update. 35 detection tests; 43 passing
overall with the VCS Connector suite.

---

## 2026-07-05 — Detection Engine: directional-rule architecture applied retroactively + R02 direction fix

**Purpose.** Apply the author's general architecture directive — directional
mechanical rules, granular evaluation, proactive fossil cleanup, strict
RF/RNF compliance — retroactively to everything built so far (VCS Connector,
engine skeleton, R02, R08), and correct R02's direction accordingly. An R03/
R04 block briefly implemented in this pass was rolled back: the author's
instruction was retroactive application first, new rules only on explicit
order.

**Key design decisions.**
- **Directional mechanical rules (author's directive, 2026-07-05).** Each rule
  detects strictly the direction its catalogue definition mandates; the
  reverse path of a one-direction refactoring introduces technical debt or
  smells and is ignored by design (empty result), aligning with DRMiner's
  approach. Where the catalogue defines complementary directions as distinct
  refactorings (e.g. Extract/Inline Stage), each direction will get its own
  rule and ID. Ambiguous directions are decided explicitly by the author,
  never inferred. The three architecture laws (directional, granular,
  non-exclusion) are now stated in the module docstring as the engine's
  contract.
- **R02 direction (author's decision, 2026-07-05; supersedes the tag
  condition described in the previous entry).** The destination tag must be
  pinned: `latest`/omitted → pinned and pinned → pinned bumps are R02;
  unpinning to `latest` (explicitly or by dropping the tag) reintroduces
  DL3007 and yields an empty result.
- **Retroactive audit results.** R02: granular ✅ (FROM subset only, stage-
  aligned), directional ✅ after the fix, entity preservation ✅. R08:
  granular ✅ (ADD/COPY subset, multiset counting), directional ✅ (reverse
  swap COPY→ADD ignored by design, test-guaranteed). Parser: CRLF-safe ✅,
  in-memory (no filesystem writes) ✅. Registry: non-exclusion in indexing
  order ✅ (RNF3: one function + one registry append per rule). VCS
  Connector: RF1 byte-identical ✅, RNF4 specific exceptions ✅, RNF5
  idempotence ✅. Fossil sweep of src/, tests/, and docstrings: no obsolete
  helpers, tests, or comments contradicting the directional architecture.

- **R08 behaviour-preservation guard (correctness bug found by the author,
  2026-07-05).** The rule fired for ADD→COPY swaps where the ADD used a
  capability COPY lacks — a remote URL source (ADD downloads; COPY cannot)
  or an auto-extractable local archive (`.tar`, `.tar.gz`, `.tgz`,
  `.tar.bz2`, `.tar.xz`; ADD unpacks, COPY copies as-is). Such a swap
  changes the build result, violating the catalogue clause ("where the
  implicit behaviours are not needed") and Fowler's behaviour-preserving
  definition. Guard added: those ADDs are excluded from the replacement
  budget, yielding an empty result. The combined `[R02, R08]` test was also
  fixed — it used `projeto.tar.gz`, which would be auto-extracted by ADD
  but not by COPY, so its swap was not a genuine R08; replaced with a
  regular file.

**Testing.** Added R02 direction tests (pinned→pinned bump positive;
unpinning to `latest`/omitted negative, both variants) and R08 guard
negatives (ADD→COPY of a `.tar.gz` archive and of an `https://` URL both
yield an empty result). 27 detection tests; 35 passing overall with the VCS
Connector suite.

---

## 2026-07-04 — Detection Engine: skeleton + R02, R08 (`src/detection_engine.py`)

**Purpose.** Analytical core of the pipeline (RF2): receives the two Dockerfile
strings and determines whether the change constitutes a recognised refactoring.
This entry covers the engine skeleton and the first rules — R02 (Update Base
Image TAG) and R08 (Replace ADD with COPY, added 2026-07-05 on the author's
go-ahead as the next easiest type); remaining rules are being added one at a
time, easy types first, each reviewed by the author before the next.

**Technology.** dockerfile-parse 2.0.1, chosen per Experiment 5 and Section 5.4:
it reconstructs multi-line RUN instructions (backslash continuation) into
logical single units, which regex line matching cannot do.

**Key design decisions.**
- Rules are independent functions registered in a central registry via a
  decorator (RNF3): adding a rule never modifies existing ones.
- Simultaneous matches follow the non-exclusion principle of the Detection
  Engine "Challenges" section of the design chapter (updated by the author,
  2026-07-05): the engine records ALL identified refactorings into a
  cumulative result list, and any deterministic resolution relies strictly
  on the rule-registry indexing order, decoupled from the quality
  dimensions. This replaced an earlier dimension-precedence scheme
  (Security > Performance > Maintainability) present in a previous revision
  of the chapter text.
- `detect_refactorings` returns a list of typed `Detection` results naming
  the refactoring and the involved instructions; the negative case returns
  an **empty list**, never a speculative match (no false positives by
  construction).
- Detection is granular, per instruction (conceptual correction by the
  author, 2026-07-05): each rule extracts its own refactoring from the
  instructions it concerns and silently ignores changes to other
  instructions in the same commit — catalogued or not. A commit is not
  required to contain the refactoring in isolation; e.g. a FROM tag update
  is R02 even if the same commit also edits a WORKDIR or an ENV. This
  replaced an initial whole-file "purity" design in which any unrelated
  change disqualified the match.
- CRLF is normalised to LF before parsing, since VCS-retrieved blobs may
  legitimately contain CRLF (see VCS Connector entry).
- `DockerfileParser` is given an in-memory `fileobj`: its default constructor
  writes a `Dockerfile` to the working directory when content is assigned,
  which would violate the no-filesystem-writes philosophy of the pipeline.
- R02 looks only at the FROM instructions, aligned by stage position, and
  reports every FROM that satisfies two named conditions: **entity
  preservation** — the base image entity is exactly the same before and
  after (identical repository name, digest, platform flags, and stage
  alias) — and a differing tag (an omitted tag counts as `latest`, so
  pinning it is R02 — decision confirmed by the author, since Docker
  resolves a missing tag to `latest` and the DL3007 smell is the same).
  The entity-preservation restriction, made explicit at the author's
  request (2026-07-05), means a changed repository name — even combined
  with a tag change, e.g. `ubuntu` → `alpine:3.18` — is a full base-image
  substitution (future R10), never R02: empty result. When the two versions
  have a different number of FROMs, stage alignment is ambiguous
  (Extract/Inline Stage territory) and the rule stays silent. The tag
  separator is the `:` after the last `/`, so registry ports
  (`registry:5000/app`) are not mistaken for tags.
- R08 evaluates only the ADD/COPY instruction subset, granularly: an ADD is
  reported as replaced when its byte-identical argument string disappears
  from the ADDs and appears among the COPYs of the after version — the
  refactoring swaps the keyword, never the sources or destination. The
  comparison is multiset-based (per-value counting), so a pre-existing COPY
  with the same arguments does not create a false positive, an ADD deleted
  without a corresponding new COPY is a deletion rather than a refactoring,
  and the reverse swap (COPY → ADD, reintroducing DL3020) is never reported.

**Problems and solutions.** None so far beyond the two anticipated pitfalls
(parser writing to disk; CRLF input), both handled as described above.

**Testing.** `tests/test_detection_engine.py` — minimal mock Before/After pair
per rule (R02 mirrors PoC-2: `ubuntu:latest` → `ubuntu:22.04`; R08 mirrors
PoC-4: `ADD app.txt /app.txt` → `COPY app.txt /app.txt`), plus parser checks
(multi-line RUN counted as one logical instruction; CRLF input parses
identically to LF) and granular-evaluation positives: tag update detected
despite unrelated WORKDIR/ENV noise; tag update detected while a RUN also
changes (replacing the abandoned whole-file "purity" negative); multi-stage
file where only the tag-only FROM is reported; ADD→COPY swap detected despite
WORKDIR/RUN noise; and the author's combined example (FROM tag update +
WORKDIR noise + ADD→COPY) yielding `[R02, R08]` in registry order. Negative
cases that must yield an empty result: identical files, base-image *name*
change (R10 territory), simultaneous name+tag change (`ubuntu` →
`alpine:3.18`, entity not preserved), stage-alias change, registry-port
lookalike, reverse swap (COPY → ADD), keyword swap with changed arguments,
ADD deletion without a new COPY, and ADD deletion next to a pre-existing
identical COPY. 23 tests, all passing (31 total with the VCS Connector
suite).

**Most relevant snippet.**

```python
@rule("R02", primary_dimension="Maintainability")
def detect_update_base_image_tag(instructions_a, instructions_b):
    changed = _changed_pairs(instructions_a, instructions_b)
    if not changed:
        return None
    for before, after in changed:
        if before.instruction != "FROM" or after.instruction != "FROM":
            return None
        pb, pa = _parse_from_value(before.value), _parse_from_value(after.value)
        if not (pb.name == pa.name and pb.tag != pa.tag
                and pb.digest == pa.digest and pb.flags == pa.flags
                and pb.alias == pa.alias):
            return None
    return Detection("R02", "Update Base Image TAG", ...)
```

---

## 2026-07-04 — VCS Connector (`src/vcs_connector.py`)

**Purpose.** Entry point of the pipeline (RF1). Given a repository path and two
commit SHAs, retrieve the Dockerfile content at each commit directly from the
Git object database — no working-tree checkout, no filesystem writes.

**Technology.** GitPython 3.1.50 on Python 3.14.6. Chosen per Experiment 3 and
Section 5.3 of the Design chapter: programmatic blob-level access is
reproducible and avoids the shell-escaping artefacts of `git show`, and a full
mining framework (PyDriller) is unnecessary for retrieving one file at two
known commits.

**Key design decisions.**
- Stateless function `retrieve_dockerfile_pair(repo_path, sha_a, sha_b, dockerfile_path="Dockerfile")`
  returning a `DockerfilePair` named tuple of two UTF-8 strings, exactly as
  specified in Section 5.3 (Design). No side effects; testable in isolation.
- The blob is read through the `data_stream` byte-stream interface
  (`commit.tree[path].data_stream.read()`) and decoded to UTF-8 — the retrieval
  path validated in Experiment 3.
- `dockerfile_path` is a parameter (default `Dockerfile` at the repo root) to
  support repositories keeping the Dockerfile in a subdirectory (Section 5.3,
  Challenges).
- Specific exceptions instead of empty strings (RNF4): `RepositoryNotFoundError`,
  `CommitNotFoundError`, `DockerfileNotFoundError`, all under a common
  `VcsConnectorError` base, so the pipeline can abort cleanly.

**Problems and solutions.** The first test run failed on Windows because the
test fixture wrote Dockerfiles with `Path.write_text`, which translates `\n`
to `\r\n`; the committed blobs therefore contained CRLF and the byte-identical
assertion failed. The connector itself was correct — it returned exactly the
bytes Git stored. Fixed by writing fixture files with `write_bytes`, keeping
the blob content exact. Noted for later components: on Windows, blob content
reflects what was committed, including CRLF line endings, so downstream
parsing must not assume LF-only input.

**Testing.** `tests/test_vcs_connector.py` — 8 offline unit tests against a
temporary Git repository built in the fixture: byte-identical retrieval of two
versions, abbreviated SHAs, subdirectory Dockerfile path, working tree left
untouched (no-checkout guarantee), idempotence of repeated calls (RNF5), and
the three error cases (RNF4). `tests/test_vcs_connector_getting_started.py` —
integration test replicating Experiment 3 against a local clone of
docker/getting-started (commits 2bca273 → 2981665), asserting the retrieved
pair differs exactly by the `--platform=$BUILDPLATFORM` / `$TARGETPLATFORM`
additions. All 9 tests pass.

**Most relevant snippet.**

```python
def _read_dockerfile_at_commit(repo: git.Repo, sha: str, dockerfile_path: str) -> str:
    try:
        commit = repo.commit(sha)
    except (git.BadName, ValueError, git.GitCommandError) as exc:
        raise CommitNotFoundError(
            f"Commit '{sha}' does not exist in repository '{repo.working_dir}'."
        ) from exc
    try:
        blob = commit.tree[dockerfile_path]
    except KeyError as exc:
        raise DockerfileNotFoundError(
            f"'{dockerfile_path}' does not exist at commit '{sha}' ({commit.hexsha[:7]})."
        ) from exc
    return blob.data_stream.read().decode("utf-8")
```
