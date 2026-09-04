# Detection — conformance of the engine against the corpus

Validates the **detection accuracy** of the engine over the whole catalogue, by
running the tool across every commit pair of the evaluation corpus and comparing
what it reported against a specification written independently of it.

The corpus is a dedicated repository of 49 commit pairs across three services,
each commit authored to exercise a defined portion of the fourteen rules. It is
not held here; it is cloned separately, and its path is given to the tool on
each invocation.

## Contents

| Path | Content |
|---|---|
| `mapping.md` | the specification: what each pair must report, and why |
| `audit_corpus.py` | compares the tool's reports against that specification |
| `execution_artifacts/pair_N/` | one folder per pair, holding the tool's output |

Each `pair_N` folder holds the `impact_report.json`, the human-readable summary,
the raw Trivy and Hadolint output, and the terminal log of that invocation.

## The four case classes

`mapping.md` assigns every pair to one of four classes, which resolve to two
expectations:

| Case class | Expectation | What it tests |
|---|---|---|
| Canonical | every listed rule must be reported | the refactoring in its textbook form |
| False-negative test | every listed rule must be reported | a syntactic variant that is easy to miss |
| Mixed | every listed rule must be reported | several refactorings in one commit |
| False-positive test | no listed rule may be reported | a change that resembles the rule without satisfying it |

A rule reported that the pair does not list is an **unlisted detection**, and
counts as an error alongside the other two: a pair conforms only when the set of
rules reported is exactly the set specified.

## Reproducing

Run **under WSL2 or Linux**. Required beforehand: `git`, `python3` (3.12 or
later), a running Docker daemon, `docker buildx`, and the Python dependencies
from the repository root (`pip install -r requirements.txt`).

**1. Clone the corpus.**

```bash
git clone https://github.com/DiogoVieira123/docker-refactoring-corpus.git /var/tmp/docker-refactoring-corpus
```

Clone it inside the WSL2 filesystem, not under `/mnt/c`. Git refuses to open a
repository owned by another user (`detected dubious ownership`), which is what a
Windows-side clone looks like to WSL2.

**2. Run the tool over each pair.** The specification in `mapping.md` gives,
for every pair, the two commit identifiers and the path of the Dockerfile it
concerns. Each pair is one invocation of the tool from the repository root,
with its output directed to the folder the audit expects. Pair 0, for
instance:

```bash
python3 main.py /var/tmp/docker-refactoring-corpus \
    7a3e568337f85fffd1e8787ca4a46f5333f39ea8 \
    a68abe73781a0708b579197055a20e6b19a56c52 \
    -d services/api/Dockerfile \
    -o "experiment and validation/detetion/execution_artifacts/pair_0"
```

The same three fields are read from `mapping.md` for each of the 49 pairs,
and the output folder is numbered to match: `pair_0` through `pair_48`. The
numbering is what the audit uses to pair a report with its specification, so
it has to correspond exactly.

`-c/--context` is not passed. Every Dockerfile in the corpus reads its `COPY`
and `ADD` sources from its own folder, which is what the tool assumes when the
option is absent, mirroring `docker build <dir>`.

Each invocation builds two images and scans them, so allow a few minutes per
pair. A pair that fails leaves no report, and the audit reports the missing
artefact rather than passing over it.

**3. Audit the results.** From this folder:

```bash
python3 audit_corpus.py
```

Add `-q` for the consolidated summary without the per-pair table. The exit
status is 0 when every pair conforms and 2 when any does not, so the audit can
gate an automated pipeline.

## Recorded result

```
Canonical             14/14
False-negative test   14/14
Mixed                  7/7
False-positive test   14/14

false negatives      : 0
false positives      : 0
unlisted detections  : 0

success rate : 49/49 (100.0%)
```

Execution and audit are kept apart on purpose. The tool reports what it
detects and writes it to disk; nothing it does consults the specification, so
a run cannot be shaped by the answer it is later measured against. The engine
never reads `mapping.md` at any point: detection is decided from the structure
of the two Dockerfile states alone. Only `audit_corpus.py` opens the
specification, and only after every report has been written.

Counts of CVEs and warnings inside each `pair_N` report move with the Trivy
vulnerability database and the Hadolint version, both recorded in the
`environment` block of each report. The rules detected do not: they are a
function of the Dockerfile pair and the engine alone, which is what this audit
measures.

## Analysis

The reading of this result — the design of the corpus, why public histories were
rejected as the primary instrument, what the false-positive controls establish
about specificity, and the threats to validity that a purpose-built corpus
carries — is presented in the evaluation chapter of the dissertation. This
folder holds the evidence, not its interpretation.
