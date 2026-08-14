# Design 

This chapter presents the design of the prototype tool proposed in this dissertation. Throughout this chapter, the term impact is used to refer to the measurable effects of refactorings on quality metrics, specifically ΔSize, ΔCVEs, ΔWarnings, and ΔInstr, consistent with the title of this dissertation, Dockerfile Refactorings: Detection and Effects. It describes the planned architecture, its design objectives, and the justification for each decision made. The chapter is grounded in the five rapid experiments conducted prior to this phase, which empirically validated the feasibility of each system component before its inclusion in the design. This approach is consistent with the Design and Development activity of the Design Science Research (DSR) methodology [11] adopted in this dissertation. 

Table 4.1 summarises the five rapid experiments, mapping each one to its objective, the method used, the observed result, and the system component whose design it grounds. The Dockerfile pairs, measurement scripts, and raw outputs of each experiment are kept in a dedicated /experiments/ folder of the project's public GitHub repository, so that every result reported below can be inspected and reproduced. 

|**#**|**Objective**|**Method**|**Result**|**Validated**<br>**Component**|
|---|---|---|---|---|
|**Exp.**<br>**1**|Validate the<br>three-axis<br>measuremen<br>t principle by<br>applying four<br>supported<br>refactorings<br>in isolation<br>and<br>confrming<br>that the four<br>deltas (Delta<br>Size, Delta<br>CVEs, Delta<br>Warnings,<br>Delta Instr)<br>capture<br>distinct<br>impact<br>profles,<br>where some|Apply each of<br>four supported<br>refactorings,<br>Inline RUN<br>Instructions<br>(R01), Update<br>Base Image TAG<br>(R02), Update<br>Base Image<br>(R10), and<br>Replace ADD<br>with COPY (R08)<br>, in isolation to a<br>minimal<br>Dockerfle pair,<br>build both<br>images, and<br>measure the<br>four deltas for<br>each pair.|The four refactorings<br>produced distinct<br>impact profles,<br>measured with<br>Hadolint unfltered.<br>Inline RUN<br>Instructions (R01)<br>reduced image size by<br>194,991 bytes and the<br>logical instruction<br>count by three, while<br>the raw warning total<br>fell from 10 to 3:<br>DL3059 (3 → 0), the<br>smell the refactoring<br>targets, together with<br>DL3008 (3 → 1) and<br>DL3015 (3 → 1), which<br>fall because four apt-<br>get invocations<br>became one. Update|The four-<br>metric<br>measureme<br>nt principle.|



|**#**|**Objective**|**Method**|**Result**|**Validated**<br>**Component**|
|---|---|---|---|---|
||refactorings<br>afect more<br>than one<br>dimension<br>and others<br>afect only<br>one.||Base Image TAG (R02)<br>eliminated the<br>DL3007 latest-tag<br>smell, taking the raw<br>total from 1 to 0.<br>Update Base Image<br>(R10, ubuntu:22.04 to<br>alpine:3.19) reduced<br>image size by<br>approximately 26.3<br>MB and removed 15<br>CVEs, improving both<br>performance and<br>security, with no<br>warning in either<br>state. Replace ADD<br>with COPY (R08)<br>eliminated a single<br>DL3020 warning with<br>a minor size increase<br>of 3 bytes and no<br>security impact. No<br>refactoring degraded<br>a dimension it was not<br>intended to afect, so<br>the trade-of fag was<br>not triggered by this<br>set.||
||Validate the<br>JSON output<br>schemas of|Run both tools<br>with --format<br>json against|Hadolint returns a fat<br>array (code, level,<br>line, message). Trivy<br>returns a nested||
|**Exp.**<br>**2**|Hadolint and<br>Trivy as<br>parseable<br>inputs for the<br>Data<br>Extractor.|<br>PoC images and<br>inspect their<br>structures<br>programmatical<br>ly.|Results[].Vulnerabiliti<br>es[] with<br>VulnerabilityID and<br>Severity. Both<br>schemas confrmed<br>stable and<br>programmatically|Data<br>Extractor|



|**#**|**Objective**|**Method**|**Result**|**Validated**<br>**Component**|
|---|---|---|---|---|
||||parseable.||
|**Exp.**<br>**3**|Validate<br>programmati<br>c access to<br>Dockerfles<br>directly from<br>the Git object<br>model,<br>without a<br>working tree<br>checkout.|Use GitPython<br>against the<br>public<br>repository<br>docker/getting-<br>started,<br>retrieving the<br>Dockerfle at<br>commits<br>2bca273 and<br>2981665.|Two distinct<br>Dockerfle versions<br>retrieved as byte<br>streams in fewer than<br>ten lines of Python<br>code.|VCS<br>Connector|
|**Exp.**<br>**4**|Validate<br>precise<br>image size<br>retrieval<br>through the<br>Docker<br>daemon API<br>rather than<br>CLI text<br>parsing.|Build a<br>Dockerfle<br>image and read<br>image.attrs['Siz<br>e'] via the<br>Docker SDK for<br>Python.|Returned 29,748,045<br>bytes (28.37 MB) as a<br>raw integer,<br>eliminating CLI<br>rounding imprecision.|Performanc<br>e Analyzer|
|**Exp.**<br>**5**|Validate<br>logical-<br>instruction<br>parsing of<br>Dockerfles,<br>including<br>multi-line<br>RUN<br>reconstructio<br>n.|Parse a<br>Dockerfle pair<br>with dockerfle-<br>parse and<br>compare the<br>resulting logical<br>instruction lists.|Four logical RUN<br>instructions correctly<br>identifed in version A<br>and one in version B;<br>the 4-to-1<br>consolidation<br>detected<br>automatically.|Detection<br>Engine|



Table Design.1 - Summary of the five rapid experiments, their objectives, methods, results, and the system components whose design they ground. 

The chapter is organised as follows. Section 4.1 provides the technical description of the system, the paradigm shift it introduces, the engineering challenges it must resolve, the functional and non-functional requirements derived from the experimental findings, the architecture design, and the verification and validation strategy. Section 4.2 presents the extended refactoring catalogue. Sections 4.3 through 4.7 describe each of the five system components in detail, justifying the technical decisions made. Section 4.8 presents the complete system data flow. Section 4.9 documents the known design limitations and planned mitigations. Section 4.10 closes with a chapter summary. 

## Prototype Tool 

### Technical Description 

The prototype tool is a Python-based analysis system that receives as input a Git repository path and two commit identifiers, extracts the Dockerfile at each commit from the version history, detects whether a structural refactoring occurred between them, identifies which of the fourteen catalogued types it corresponds to, and produces an impact report quantifying the change across four metrics: ΔSize, ΔCVEs, ΔWarnings, and ΔInstr. The extended catalogue of Section 4.2 is a conceptual taxonomy: it names and organises the refactoring types and records, from the literature and from controlled experiments, the quality directions each one is expected to produce. The prototype does not consult that taxonomy at run time. It detects the transformation, reports its formal identifier, and measures what the two Dockerfile states actually produce, without any expectation of the outcome being encoded in the software. The catalogue is therefore the reference against which results are read, not an input to the computation. 

The selection of Python 3 as the implementation language was determined by the rapid experimentation phase: all five experiments were conducted in Python, and the libraries validated in those experiments, GitPython, dockerfile-parse, and the Docker SDK, are all Python-native. This eliminates any interoperability risk that would arise from selecting a different language and ensures that the prototype can be built directly on top of the validated experimental scripts. 

The interaction with the Docker daemon is handled exclusively through the Docker SDK for Python [Exp. 4], which communicates directly with the daemon via the Unix socket and returns image sizes as raw byte integers. This is architecturally preferable to parsing the output of the Docker CLI, which rounds values and introduces imprecision. Experiment 4 confirmed that this call returns an exact byte count, 29,748,045 bytes (28.37 MB) for the documented public test image (ubuntu:22.04) used in that experiment, a precision level that would be rounded away by the CLI. This precision is essential because the Performance Analyzer computes the size delta by subtracting two such byte counts, and CLI rounding would distort small deltas. 

Version history access is handled by GitPython [Exp. 3], which navigates the Git object model natively, retrieving the Dockerfile content at any commit as a byte stream without requiring a working tree checkout or filesystem write operations. Experiment 3 validated this approach against the public repository docker/getting-started (commits 2bca273 and 

2981665), confirming that two distinct Dockerfile versions can be retrieved correctly with fewer than ten lines of Python code. 

Dockerfile parsing is handled by the dockerfile-parse library [Exp. 5], which reconstructs multi-line RUN instructions, those split across physical lines using the backslash continuation character, into their logical single-unit representation. This reconstruction is critical for the Detection Engine: without it, a single logical command spread over eight lines would be miscounted as eight instructions, producing false detection results. Experiment 5 confirmed that the library correctly identifies four logical RUN instructions in a Dockerfile where they span multiple physical lines, and one logical instruction in the consolidated version. 

Security and Maintainability metrics are collected using Trivy and Hadolint [10] respectively, both of which were validated in Experiment 2 with JSON-formatted output. Trivy scans the built Docker image for known CVEs, producing a structured results array with vulnerability identifiers and severity levels. Hadolint performs static analysis on the Dockerfile text, producing a flat array of rule violation objects. Experiment 2 confirmed that both schemas are stable and programmatically parseable, providing the foundation for the Data Extractor component. 

### Planned Changes in the System 

The current state of Dockerfile maintenance is characterised by the absence of systematic feedback. When a developer applies a refactoring, whether consolidating RUN instructions, updating a base image, or adding cache cleanup, the impact of that change on image size, vulnerability exposure, and structural quality is never actually measured, since decisions are typically based on general knowledge of best practices rather than on empirical evidence. This lack of systematic verification means that improvements are assumed rather than confirmed, leaving the real effects of the applied refactoring unknown. 

The prototype tool addresses this gap by introducing a systematic measurement cycle, replacing this opacity with quantifiable evidence of the actual impact produced. For each pair of commits where a refactoring is detected, the system computes four delta values across the three quality dimensions: ΔSize (the change in image size in bytes and as a percentage), ΔCVEs (the change in vulnerability count by severity level), ΔWarnings (the change in Hadolint rule violations classified by quality dimension), and ΔInstr (the change in the number of logical instructions). Maintainability is the only dimension measured by two indicators, for the reasons set out in Section 4.1.3: ΔWarnings reports the change at the smell level, while ΔInstr reports it at the structural level. Together, these values constitute the empirical evidence base for what a refactoring actually achieved. 

Four isolated proof-of-concept experiments were conducted prior to this design phase to establish empirical baselines for each delta metric. Each experiment applied a single refactoring to a minimal Dockerfile pair, ensuring that observed deltas are attributable to the refactoring under test and not to confounding changes. All four were executed in a single run on 17 July 2026, using Docker 29.1.3, Hadolint 2.14.0, Trivy 0.72.0, and dockerfile-parse 2.0.1. 

The purpose of this set is to show that a refactoring moves the quality dimensions it is expected to move, in a real build rather than in principle. The absolute values reported below are the measurements obtained in that run, and they are given so that each delta can be traced back to the pair it came from. They are not catalogue reference values: registries republish tags and Trivy updates its vulnerability database daily, so a later run may return different absolute figures without invalidating anything reported here. What the proof-of-concept set establishes is the practical viability of the measurement approach and the direction of each effect, and both hold independently of the run. Producing values that are comparable across refactoring types is the separate purpose of the controlled catalogue experiments of Section 4.2, which are conducted under their own conditions and are not derived from this set. 

PoC-1 — Inline RUN Instructions (R01): The consolidation of four distinct RUN commands into a single chained command resulted in a Delta Size of −194,991 bytes (117,254,883 → 117,059,892), a Delta CVEs of 0 (26 → 26, unchanged at 12 MEDIUM and 14 LOW), and a Delta Instr of −3 (5 → 2). For the proof-of-concept set Hadolint runs without any rule filter, so the reported figure is ΔWarnings (total raw): it fell from 10 to 3, a difference of −7. The reduction decomposes into DL3059 (3 → 0), the consecutive-RUN smell the refactoring directly targets, together with DL3008 (3 → 1) and DL3015 (3 → 1), which fall because the four apt-get invocations that each violated those rules became one; DL3009 was 

unchanged at 1. This total aggregates rules across quality dimensions and is reported to demonstrate detection sensitivity, not as the filtered maintainability indicator defined in Section 4.1.3. 

PoC-2 — Update Base Image TAG (R02): Replacing the mutable ubuntu:latest tag with the explicit ubuntu:22.04 tag produced a Delta Size of −11,845,577 bytes (41,593,622 → 29,748,045), a Delta CVEs of −26 (45 → 19), a Delta Instr of 0 (1 → 1), and a ΔWarnings (total raw) of −1, falling from 1 to 0 and accounted for entirely by the elimination of DL3007, effectively removing the "latest-tag" anti-pattern. The severity distribution improves alongside the total: the before state carries 5 HIGH, 34 MEDIUM, 4 LOW and 2 UNKNOWN, while the after state carries 9 MEDIUM and 10 LOW, so every HIGH severity vulnerability is removed. At execution time the ubuntu:latest tag was resolved to the explicit manifest it pointed to, and the before figures describe that state; because the tag is mutable, a later run may resolve to a different manifest and return different absolute values. The elimination of DL3007 is invariant across runs, and the direction of the size and CVE deltas follows from the substitution itself rather than from the particular version the tag happened to resolve to. 

PoC-3 — Update Base Image (R10): Replacing the ubuntu:22.04 base image with the minimal alpine:3.19 image produced a Delta Size of −26,318,550 bytes (29,748,045 → 3,429,495), a Delta CVEs of −15 (19 → 4), and a Delta Instr of 0 (1 → 1). Neither state produced any Hadolint warning under the unfiltered count, so ΔWarnings (total raw) is 0: this refactoring acts on the base image rather than on any pattern Hadolint inspects. This is the most impactful refactoring in the set, showing that the choice of base image moves performance and security at the same time. One qualification applies to the security figure. The total falls from 19 to 4, but the before state carries no HIGH severity 

vulnerability (9 MEDIUM, 10 LOW) while the after state carries one (1 HIGH, 2 MEDIUM, 1 LOW), so the severity distribution changes as well as the total, and a smaller image is not automatically a safer one. Because Trivy updates its vulnerability database daily, the absolute counts belong to the run reported here; what the experiment establishes is the direction and the scale of the change. 

PoC-4 — Replace ADD with COPY (R08): Working on the same alpine:3.19 base used in PoC-3, replacing an ADD instruction that copies a regular file with the equivalent COPY instruction produced a Delta Size of +3 bytes (3,421,509 → 3,421,512), a Delta CVEs of 0 (4 → 4, unchanged at 1 HIGH, 2 MEDIUM and 1 LOW, the profile inherited from that base), a Delta Instr of 0 (2 → 2), and a ΔWarnings (total raw) of −1, falling from 1 to 0 and accounted for entirely by the elimination of DL3020. The change is purely structural, eliminating the implicit-extraction risk associated with ADD without affecting image size or vulnerability exposure. 

The prototype automates the entire measurement process, transforming what required manual invocation of three separate tools into a single programmatic call. 

### Metric Selection and Scope 

The three quality dimensions are operationalised through metrics that can be computed automatic  ally for any Dockerfile pair. Performance is measured by image size (ΔSize), retrieved in bytes through the Docker SDK. Security is measured by the CVE count reported by Trivy (ΔCVEs). Maintainability is measured by two indicators rather than one: the Hadolint warning count (ΔWarnings) and the logical instruction count (ΔInstr). Throughout, ΔWarnings refers to this filtered count. Where a broader count of all Hadolint rules is reported, it is used as context to show that a smell was eliminated, and never as the metric itself. 

Two warning-counting regimes are used in this work, and the distinction is deliberate rather than incidental. The extended catalogue experiments apply a maintainability screen of 47 rules: those enabled by default in Hadolint and ShellCheck whose effect is on reproducibility, structural correctness, instruction usage and notation, metadata, shell correctness, or build logs. Rules whose effect is on image size, such as cache cleanup or RUN consolidation, are excluded because that effect is already measured by ΔSize; rules whose effect is on attack surface are excluded for the same reason with respect to ΔCVEs. Without this screen, a single refactoring that reduces image size would be counted twice, once in ΔSize and again in ΔWarnings, and the dimensions would cease to be independent. 

The four proof-of-concept experiments of Section 4.1.2 are the single exception. There Hadolint runs unfiltered and the raw total is reported, because their purpose is different: they are exploratory sensitivity checks establishing that the pipeline detects warning changes at all and attributes them to the correct rules, before any dimensional interpretation is placed on the count. Proof-of-concept warning totals are labelled "total raw" wherever they appear and are never used as the maintainability indicator. The consequence is visible in PoC-1, where the raw total falls by seven but only two of those eliminations, both of DL3008, belong to the maintainability screen; the remaining five belong to rules whose effect is already captured by ΔSize. Reporting the raw total there measures the reactivity of the instrument, not the maintainability of the Dockerfile. 

The second maintainability indicator exists because the correspondence between dimensions and metrics is not symmetric. ΔSize and ΔCVEs are direct measurements of the built image: each reads a property of the artifact the Dockerfile produces. ΔWarnings works differently. It counts violations of a predefined rule set, so it only reacts when a refactoring happens to match a rule that Hadolint implements. However, many structural improvements, such as simplifying the Dockerfile logic, do not necessarily trigger a reduction in Hadolint warnings. For these cases, _Δ_ Warnings stays at zero, not because the refactoring failed to improve maintainability, but because the tool’s static analysis is not designed to measure structural complexity. Since maintainability is the dimension most often affected across the catalogue (Table 4.3), relying on ΔWarnings alone would leave the most frequently affected axis largely unmeasured. 

ΔInstr addresses this at a different level. Hadolint reports smells; the instruction count reports structure. Wu et al. [8] use the number of instructions in a Dockerfile as a proxy for its complexity, treating it as an independent variable in their regression models of smell occurrence. The same reasoning applies here: a refactoring that removes a redundant stage, or that eliminates instructions whose only purpose was to move files, leaves a structurally simpler Dockerfile, and that simplification shows up in the instruction count even when no Hadolint rule fires. 

Three properties made ΔInstr preferable to the alternative considered. It requires no external tool: the count is obtained by parsing each Dockerfile state with dockerfile-parse, a Python library already part of the prototype, so no container has to be built or scanned and no subprocess has to be invoked to produce it. It keeps the maintainability dimension from depending on a single instrument, since Hadolint is embedded in the prototype and cannot serve as its own reference. And it operates on logical instructions rather than physical lines of code (LOC): a single RUN split across eight lines with backslash continuations would be counted as eight lines by a LOC measure but represents one logical instruction, so the logical count stays insensitive to formatting. This follows the theoretical advantage that Park [24] recognises in logical statement counts, namely their relative independence from formatting style, which is the property that matters when the goal is to measure structural change rather than physical layout. 

#### **Reading ΔInstr** 

The sign convention applied to ΔSize, ΔCVEs, and ΔWarnings, where a negative delta means improvement, does not transfer to ΔInstr. Refactorings act on the instruction count in three distinct ways, and each has to be read against the operation that produced it: 

- **Consolidation and removal reduce the count.** Inline RUN Instructions (R01), Inline Stage (R06), and Remove RUN (R12) leave fewer instructions, and the reduction is a structural gain. 

- **Extraction and addition increase it:** Add ENV Variable (R03), Add ARG Instruction (R04), Extract Stage (R05), Extract RUN Instructions (R09), and Move Stage (R11) introduce instructions on purpose. An ENV that centralises a version number adds one instruction and still makes the file easier to maintain, which is the point of the refactoring; extracting a RUN block into a script or a stage into its own file works the same way. 

- **Some refactorings leave it unchanged:** Update Base Image TAG (R02), Sort Instructions (R07), Replace ADD with COPY (R08), Update Base Image (R10), Update RUN Instruction (R13), and Rename Image (R14) act on arguments, order, or formatting, so the count is identical before and after. 

ΔInstr is therefore reported as a structural indicator interpreted per refactoring type, and not as a score to be minimised. 

#### **Refactorings at the limit of quantitative reach** 

Two refactorings sit at the edge of what the four metrics can register, and each does so for a different reason. Update RUN Instruction (R13) reformats a RUN by splitting it across lines and ordering its arguments; the controlled experiment measured a size increase of 16 bytes (11,100,915 → 11,100,931), reflecting the longer command string stored in the image configuration, a variation that falls well below the relevance threshold. Rename Image (R14) replaces numeric stage references with readable identifiers and measured no change at all (3,632,095 → 3,632,095), the only exact null size delta in the catalogue. On the remaining indicators both behave the same way: the vulnerability count is stable across states, 146 for R13 and 77 for R14, each measured on a non-null debian:12-slim baseline; neither matches a Hadolint rule, so ΔWarnings is zero; and neither adds or removes a logical instruction, so ΔInstr is zero. What the metrics do not capture is the benefit that motivates both refactorings, which is readability. This is reported as a genuine result rather than treated as a gap: inventing a readability metric for two refactorings would weaken the measurement approach instead of strengthening it. The maintainability classification of both rests on the nature of the operation, discussed in Section 4.2.3. 

### Challenges 

Three engineering challenges shaped the design of the prototype and must be resolved for the system to produce reliable results. 

The first challenge is multi-line RUN instruction parsing. Dockerfiles commonly express a single logical shell command across multiple physical lines using the backslash continuation character. A parser that operates at the line level will fragment a single logical RUN instruction into multiple tokens, causing incorrect instruction counts and false refactoring detections. The dockerfile-parse library resolves this by exposing logical instruction objects regardless of their physical line count, as validated in Experiment 5. The Detection Engine is designed to operate exclusively on this normalised representation. 

The second challenge is JSON schema heterogeneity. The Data Extractor must aggregate metrics from two tools with incompatible output structures. Hadolint produces a flat array of warning objects with fields code, level, line, and message. Trivy produces a deeply nested structure with a Results array, each element of which contains a Vulnerabilities sub-array. A delta computation that is arithmetically valid requires both schemas to be normalised into a common internal representation before any comparison is performed. Experiment 2 confirmed the structure of both schemas, providing the ground truth for this normalisation design. 

The third challenge is consolidation-versus-deletion ambiguity. When the count of RUN instructions decreases between two commits, the change may represent a pure consolidation, a pure deletion, or a mixed commit combining instruction inlining with concurrent code cleanup. These operations have distinct structural implications. To accommodate real-world developer practices where refactorings and minor cleanups frequently overlap, the Detection Engine employs a fusion-proof criterion rather than a 

strict preservation check. It searches for positive evidence of instruction merging: if the primary command blocks are effectively combined into a surviving instruction, the change is classified as a consolidation refactoring and triggers the R01 rule even if minor adjacent commands or cleanups were simultaneously deleted. Conversely, if the reduction in instruction count stems from a pure deletion without any structural fusion, the change is classified as a deletion and is not reported as a refactoring. 

### Functional and Non-Functional Requirements 

The functional requirements are derived directly from the experimental findings and are organised by system component. 

RF1 — VCS Connector: The system shall extract the complete textual content of the Dockerfile at two user-specified commits from a local Git repository, using programmatic blob-level access without requiring a working tree checkout. [Validated in Experiment 3]. Acceptance criterion: Dockerfile content retrieved at two commits is byte-identical to the content stored in the Git object database 

RF2 — Detection Engine: The system shall parse both Dockerfiles into their canonical logical instruction representations and determine whether the structural change between them constitutes a supported refactoring type. For each detection, the engine shall identify the specific instructions involved. [Validated in Experiment 5]. Acceptance criterion: the 4-to-1 RUN consolidation from Experiment 5 is detected automatically from the parsed instruction lists. 

RF3 — Detection Engine: The system shall assign to each detected transformation the formal identifier of the corresponding catalogue type (R01–R14) and emit a typed DetectionResult carrying that identifier together with the instructions involved. The identifier is a label attached to the detection and carries no quality expectation: no impact value is read from the catalogue at this or any later stage, and the metric deltas are computed independently by the Performance Analyzer and the Data Extractor from the two Dockerfile states. Acceptance criterion: the Dockerfile pair for R06 (Inline Stage) produces a DetectionResult carrying the identifier R06 and the stage instructions involved, with no impact field populated. 

RF4 — **Performance Analyzer:** The system shall build the Docker image for each Dockerfile state and retrieve the image size in bytes via the Docker SDK, returning a signed delta ( _Δ_ Size) expressed in bytes. [Validated in Experiment 4]. Acceptance criterion: PoC-3 test — Delta Size correctly computed between Dockerfile A (ubuntu:22.04) and Dockerfile B (alpine:3.19): the image size is reduced from 29.7 MB to 3.4 MB, a difference of 26.3 MB. At byte resolution the Docker SDK reports this as a signed Delta Size of −26,318,550 bytes (29,748,045 → 3,429,495 bytes). 

RF5 — Data Extractor: The system shall invoke Hadolint and Trivy against each image state using JSON output mode, normalise their heterogeneous schemas into a common metric representation, and return the warning count delta (ΔWarnings) and CVE count delta (ΔCVEs) by severity tier. The CVE count shall be the number of distinct vulnerability identifiers reported by Trivy, not the number of occurrences, so that a single vulnerability 

affecting several packages is counted once. The warning count shall encompass all maintainability-related rule violations reported by Hadolint, capturing the global sum of warnings to reflect the overarching maintainability health of the Dockerfile, thereby ensuring a universal evaluation independent of specific rule constraints. [Validated in Experiment 2 and PoC tests PoC-2, PoC-3]. Acceptance criteria: PoC-2 test — correctly computes the warning delta for the test scenario, yielding −1 for DL3007; PoC-3 test — correctly computes the CVE delta from the Trivy JSON output, with the reference value of −15 reflecting the specific database state at the time of the test run rather than a fixed global constant. 

RF6 — Data Extractor: The system shall count the logical instructions of each Dockerfile state, excluding COMMENT entries, and return the signed difference (ΔInstr) as a structural maintainability indicator reported alongside ΔWarnings. The count shall be derived from the textual content of the Dockerfile through dockerfile-parse, and not from the built image, so that multi-line instructions joined by backslash continuations resolve to a single logical unit. Acceptance criteria: R06 test — $\Delta\text{Instr} = -3$ correctly computed; PoC-4 (R08) test — $\Delta\text{Instr} = 0$ for a refactoring that reorganizes or replaces instructions without changing the total logical instruction count. 

RF7 — Report Generator: The system shall produce a structured output presenting the before and after values for each quality metric along with the computed metric deltas (delta_size, delta_warnings, delta_cves, delta_logical_instructions) associated with the detected refactoring rules for the target Dockerfile. Acceptance Criterion: The generated report correctly displays the initial metric values, final metric values, and calculated deltas for all four measured metrics alongside the corresponding detected rule IDs. 

RNF1 — Metric Precision: The Performance dimension shall be quantifiable at byte-level resolution sufficient to detect significant size reductions. Acceptance criterion: PoC-3 test — the Docker SDK returns the exact byte size of each image, so the 26.3 MB reduction is preserved at full resolution as −26,318,550 bytes rather than being rounded away by CLI text parsing. 

RNF2 — Diagnostic Sensitivity: The two maintainability instruments shall each be sensitive enough to detect a change in the property they measure. At the smell level, Hadolint shall detect the complete elimination of a relevant rule violation; at the structural level, the parser shall detect the addition or removal of a single logical instruction. Sensitivity is a property of the instruments and not a claim of coverage: as stated in Section 4.1.3, neither indicator spans the full set of maintainability subcharacteristics defined by ISO/IEC 25010 [25], and the requirement asserts only that each responds to the changes it is designed to register. Acceptance criteria: PoC-2 test — Delta Warnings(DL3007) = -1 correctly detected, representing complete elimination of the mutable-tag smell between Dockerfile A (ubuntu:latest) and Dockerfile B (ubuntu:22.04); R06 test — Delta Instr = -3 correctly detected on a refactoring that registers an improvement on the maintainability axis. 

RNF3 — Extensibility: The Detection Engine rule set shall be extensible to new refactoring types without modification of existing component code, following the Open-Closed 

Principle [26]. Each rule is self-contained and registered in a declarative rule list, so that adding a type requires an addition to that list and no change to the execution logic of any component. The prototype supports fourteen types; the architecture must accommodate additional types in future iterations. Acceptance criterion: a new detection rule can be added to the registry and exercised end to end without editing any existing rule or any downstream component. 

RNF4 — Reliability: All external invocations, Docker SDK, Hadolint, Trivy, and the parsing of Dockerfile content shall be wrapped in exception handlers that distinguish recoverable errors from unrecoverable failures and surface informative diagnostic messages. Acceptance criterion: build failure, daemon error, missing Dockerfile, and malformed Dockerfile content each produce a distinct informative exception. 

RNF5 — Reproducibility: The system shall record, in every report, the analysis timestamp, the version of each external tool invoked (Docker Engine, Hadolint, Trivy, dockerfileparse), and the Trivy vulnerability database version, enabling future re-runs to identify whether differences in CVE counts are attributable to Dockerfile changes or to database updates. Furthermore, reproducibility is ensured not only by these records but also through the capability to retain the source analysis artifacts generated by external tools during the extraction phase. Acceptance criterion: every generated report contains the analysis timestamp, the tool version block, the Trivy vulnerability database version, and the retained source analysis artifacts. 

### Architecture Design 

The prototype tool is structured as a sequential data pipeline composed of four logical stages, where each stage transforms a well-defined input into an output consumed by the next. This architecture enforces the strict causal dependency chain required by the analysis: version retrieval (Stage 1) must precede refactoring detection (Stage 2), which in turn provides the context for the empirical evaluation (Stage 3) and the final report generation (Stage 4). The sequential pipeline ensures deterministic, reproducible execution consistent with RNF5. 

The pipeline is expressed as the following transformation sequence, defining the execution order: 

- **Stage 1 — Data Collection:** Retrieves the Dockerfile content from the version history via the VCS Connector. 

- **Stage 2 — Refactoring Detection:** Parses the Dockerfiles and identifies the transformation using the Detection Engine. 

- **Stage 3 — Empirical Evaluation and Measurement:** Performs the build and analysis. This stage relies on the Image Builder mechanism to reconstruct the environment, while the Performance Analyzer and Data Extractor execute in parallel to collect performance, security, and maintainability metrics. 

- **Stage 4 — Report Generation:** Aggregates the results into the final ImpactReport. 

Three architectural approaches were considered. An event-driven architecture was rejected because it cannot enforce the strict causal dependency chain required by this analysis: each stage depends on the typed output of the previous stage, version extraction must produce Dockerfile strings before detection can operate, and detection must produce a DetectionResult before the measured deltas can be paired with it. A component that consumes an event before its predecessor has completed would receive incomplete data, producing unreliable results. A service-oriented architecture was rejected because exposing each pipeline stage as an independent network service would introduce inter-service communication overhead and interoperability risks that contradict the Python-native design constraint established during the rapid experimentation phase. The sequential pipeline was selected because MSR-based analysis inherently follows a structured sequence of repository selection, data extraction, and analysis steps [20], and this architecture maps directly onto the validated experimental scripts, enforces the causal ordering of operations, and ensures that identical inputs always produce identical outputs. 

The pipeline is expressed as the following transformation sequence, which defines the execution order of the components: 



<!-- Start of picture text -->
Git repository<br>SHA_A+ 5HA_B<br>STAGE 1 —| COLLECTION<br>VCS Connector<br>GitPython<br>STAGE 2 —|<br>Detection Engine<br>dockerfile-parse<br>I \<br>STAGE 3 — EMPIRICAL EVALUATION |<br>Data Extractor<br>Perf.. neon Analvee, Hadolint - Trivy -<br>fener we dockerfile-parse<br>Ns STAGE 4 — REPORT A<br>Report Generator<br>ageregation<br>| ImpactReport<br><!-- End of picture text -->



<!-- Start of picture text -->
Dockerfile_A, Dockerfile |B DetectionResult<br>Detection Engine<br>VCS Connector<br>' H dockerfile-parse '<br>EEE are (eee<br>t H eee eee<br>' GitPython '<br>MetricSet (size)<br>Performance Analyzer Report Generator<br>aaatt DockeraaSDK aa'{<br>Data Extractor ImpactReport<br>ASize ACVEs AWarn Alnstr<br>MetricSet<br>H (warnings, CVEs, instr)<br>Pe ER NAEP AE ET RenOE<br>|I Hadolint- Trivy: dockerfile-parse '|<br><!-- End of picture text -->

Dashed boxes are external tools. The Detection Engine and the Data Extractor invoke dockerfile-parse independently, for detection and for the instruction count respectively. 



<!-- Start of picture text -->
Dockerfile Refactoring Analysis Tool<br>Analyse the refactoring applied<br>between two commits of a Dockerfile<br>inputs: repository path, SHA_A, SHA_B<br>Developer / Researcher<br>The analysis runs to completion without further interaction and returns the impact report in JSON.<br><!-- End of picture text -->



<!-- Start of picture text -->
<<device>> Host machine <<execution environment>> Docker daemon<br>Prototype application Docker SDK A rn<br>Python 3 Hadolint Trivy<br>VCS Connector - Detection Engine container (pinned) container (pinned)<br>Performance Analyzer - Data Extractor Unix socket<br>Report Generator<br>CCGi'ca aa<br>qGit repository (working copy) :<br>q ‘ Image _ A Image B<br>PSS a SS 0 NAS C built from Dockerfile_A built from Dockerfile_B<br>ImpactReport (JSON) Hadolint analyses the Dockerfile text; Trivy scans the two built images;<br>the Docker SDK reports image size in bytes.<br><!-- End of picture text -->

|**Component**|**Responsibility**|**Validated**<br>**Technology**|**Satisfes**<br>**Requirements**|
|---|---|---|---|
|**Analyzer**|size in bytes via daemon API|Exp. 4||
|**Data Extractor**|Invokes static and security<br>tools, counts logical<br>instructions, and normalises<br>metrics|Hadolint + Trivy —<br>Exp. 2; dockerfle-<br>parse|RF5, RF6, RNF2,<br>RNF4, RNF5|
|**Report**<br>**Generator**|Aggregates the detected<br>identifer with the metric<br>deltas and produces the<br>ImpactReport|Rule-based<br>computation|RF7, RNF5|



Table Design.2 - Prototype components, their responsibilities, technologies, and satisfied requirements. 

### Verification and Validation Strategy 

The verification and validation strategy for the prototype is structured across three levels, consistent with standard software engineering practice. 

At the unit level, each pipeline component is tested in isolation using the inputs and expected outputs established during the controlled multi-dimension experiments. For example, the Detection Engine unit test verifies that the Dockerfile pair for R06 (Inline Stage) is correctly identified and that the emitted DetectionResult carries the R06 identifier. The Report Generator unit test verifies that the four deltas are computed from the two MetricSet objects and paired with that identifier without alteration. 

At the integration level, the interfaces between components are validated by running the complete pipeline against each of the four controlled multi-dimension experiment Dockerfile pairs (R06, R09, R11, and R12) and verifying that the typed data structures, DetectionResult, MetricSet, ImpactReport, are correctly produced and consumed at each boundary as specified in Table 4.2. 

At the system level, end-to-end behavior is validated against the four controlled multidimension experiment scenarios (R06, R09, R11, and R12), all executed using an alpine:3.20 base image. The expected reference values are: 

- **R06 (Inline Stage)** — _Δ_ Size=+116 bytes (3,632,710 → 3,632,826), _Δ_ CVEs=0, _Δ_ Warnings=0, _Δ_ Instr =-3 (8 → 5); 

- **R09 (Extract RUN Instructions)** — _Δ_ Size=+417 bytes (3,633,775 → 3,634,192), _Δ_ CVEs=0, _Δ_ Warnings=0, _Δ_ Instr =+1 (5 → 6); 

- **R11 (Move Stage)** — _Δ_ Size=+1 byte (3,632,724 → 3,632,725), _Δ_ CVEs=0, _Δ_ Warnings=0, _Δ_ Instr =+1 (8 → 9); 

- **R12 (Remove RUN (mv))** — _Δ_ Size=-1,331 bytes (3,634,927 → 3,633,596), _Δ_ CVEs=0, _Δ_ Warnings=0, _Δ_ Instr =-2 (8 → 6). 

Divergence from these reference values indicates a regression in the pipeline. These reference values serve as regression anchors for the implementation phase described in Chapter 5. 

## Extended Refactoring Catalogue 

Each rule in the Extended Catalogue is evaluated across all three quality axes, Performance, Security, and Maintainability, forming a complete three-dimensional impact vector. This approach provides a transparent overview of what a transformation is intended to achieve and of any degradation it introduces on the remaining axes: 

|**ID**|**Rule**|Perfomance|**Security**|Maintainability|
|---|---|---|---|---|
|**R01**|Inline RUN Instructions|↑|X|↓|
|**R02**|Update Base Image TAG|↑*|↓|↑|
|**R03**|Add ENV Variable|X|↓|↑|
|**R04**|Add ARG Instruction|X|↓|↑|
|**R05**|Extract Stage|↑|↑|↑|
|**R06**|Inline Stage|X|X|↑|
|**R07**|Sort Instructions|↑|X|↓|
|**R08**|Replace ADD with COPY|X|↑|↑|
|**R09**|Extract RUN Instructions|X|X|↑|
|**R10**|Update Base Image|↑|↑|↑|
|**R11**|Move Stage|X|X|↑|



|**ID**|**Rule**|Perfomance|**Security**|Maintainability|
|---|---|---|---|---|
|**R12**|Remove RUN Instruction<br>(mv)|X|X|↑|
|**R13**|Update RUN Instruction|X|X|↑|
|**R14**|Rename Image|X|X|↑|



Table Design.3 - Extended Dockerfile refactoring catalogue mapping fourteen types across three quality dimensions 

Methodological note on the relevance threshold. For performance evaluation purposes in this research, a 1 MB threshold was established. This order of magnitude reflects the scale of analysis typically used in the specialized literature to size Docker images (where variations and reductions are inherently reported in Megabytes). Residual dimensional variations below 1 MB fall below the operational granularity of the artifact, presenting a null impact on storage, network, or startup time. Consequently, they were methodologically classified as neutral (X). 

A crucial conceptual distinction must be established regarding the quality dimensions assigned to the refactoring types within the Extended Catalogue (Table 4.3). The directional impact values mapped across the three quality dimensions, Performance, Security, and Maintainability, for each rule represent a theoretical propensity or strategic intent derived from software engineering literature and documented best practices (which are presented, discussed, and individually cited for each refactoring rule detailed below, from R01 to R14), i.e., what a structural transformation is conceptually designed to achieve in an ideal, isolated setting. Rather than assuming a rigid primary focus, each refactoring is evaluated through a three-dimensional impact vector, where individual dimensions are classified as improved (⬆️�), degraded (⬇️�), or neutral (❌). This multi-axial structure explicitly captures potential directional compromises and side effects of a transformation across independent quality axes without imposing a hierarchical ranking between them. 

However, the evaluation pipeline is built to capture the empirical reality of software evolution. When implemented in a real-world DevOps environment, a refactoring operation behaves as a necessary but not sufficient condition for quality improvement. While the detection engine successfully validates the structural and syntactic alignment of a change against the catalogue, the developer remains responsible for the semantic parameters supplied to that instruction. If a structurally correct refactoring is executed with obsolete, insecure, or poorly configured arguments, external tools will register a local degradation in performance or security metrics. 

Consequently, an empirical divergence between the catalogue’s classification and the tool’s computed deltas does not invalidate the taxonomy. Instead, it exposes the operational friction between structural intent and semantic execution, reinforcing the 

utility of the prototype as an objective auditing mechanism capable of surfacing measurable quality impacts when developer decisions diverge from theoretical benefits. 

This separation is what makes the tool an auditing instrument rather than a confirmation of its own taxonomy. The pipeline holds no table of expected impacts, no dictionary keyed by refactoring type, and no lookup performed while an analysis is running. It builds both images, scans both, parses both, and reports the four deltas it obtains. A result that contradicts the direction recorded in Table 4.3 is therefore a finding about the build environment or about the transformation as applied in that specific case, and never an inconsistency inside the software. Keeping the theoretical mapping outside the code is also what allows the catalogue to be revised without touching the prototype, and the prototype to be run against refactorings whose quality direction is still open. 

The remainder of this section develops the technical justification for each classification in Table 4.3. For each refactoring, the dimensions are supported either by empirical evidence from the literature or, where no such evidence exists, by a controlled experiment designed for this dissertation (described in Section 4.2.1 and available in the project repository). Each justification also notes any relevant trade-off across quality dimensions. 

#### **R01 — Inline RUN Instructions** 

**Performance ↑.** Rosa et al. [17] identify DL3059 as the smell most frequently fixed by developers in open-source projects, with 168 manually validated fixes, approximately three times more frequent than any other fix. The study reports that these fixes were "explicitly performed to reduce the Docker image size and the number of layers". Ksontini et al. [2] independently classify Inline RUN Instructions under the Image Size category, observing it in four commits of their corpus. 

**Security X.** The controlled experiment on debian:12-slim measured a stable vulnerability count of 146 in both states (ΔCVEs = 0). Because the baseline is non-null, this value is a measurement rather than an absence of data: consolidating consecutive RUN instructions alters the layer structure without changing which packages are installed or their versions, so the attack surface is unaffected. 

**Maintainability ↓.** Nüst et al. [16] observe that a single lengthy RUN instruction chaining multiple commands "creates instructions that may be hard to read", and recommend that each RUN perform one scoped action, since reasonably grouped instructions increase the readability of the Dockerfile. The performance gain therefore carries a legibility cost. 

#### **R02 — Update Base Image TAG** 

**Performance ↑* (not attributable).** The controlled experiment measured a size reduction of 11,845,577 bytes (41,593,622 → 29,748,045), a numerically substantial improvement of approximately 28% and the only measured variation in the catalogue above the relevance threshold. It is nevertheless reported under a distinct symbol because it constitutes a threat to validity rather than a clean measurement of the refactoring. The before state uses the floating tag ubuntu:latest, whose resolution changes whenever the publisher rebuilds the image: the magnitude observed reflects the difference between whichever version latest pointed to at build time and the pinned ubuntu:22.04, not an effect produced by the transformation itself. A subsequent execution of the identical pair may yield a different magnitude, or a positive delta, if latest resolves to a smaller image than the pinned tag. The improvement is real for this run and not reproducible across runs, 

which is precisely the property that motivates the refactoring in the first place, and the reason the size delta cannot serve as a stable reference value. 

**Security ↓.** The Docker Documentation [7] states that when pinning an explicit version "you're opting out of automated security fixes, which is likely something you want to get", and recommends the opposite practice for security: "To keep your images up-to-date and secure, rebuild your images regularly with updated dependencies." Building on that warning and on Zerouali et al. [27], who found across 7,380 Debian-based images that the number of outdated packages is strongly correlated with the number of resolved vulnerabilities (ρ > 0.9), and that the most vulnerable containers were those not updated for more than two years, pinning without a regular update procedure accumulates exposure over time. The effect is moderated rather than absolute: the same study notes that no release is devoid of vulnerabilities, so currency alone does not eliminate them. 

**Maintainability ↑.** Rosa et al. [17] report a 64% acceptance rate for DL3007 fixes submitted as pull requests. The Docker Documentation [7] gives the underlying rationale: with a mutable tag "you're not guaranteed to get the same for every build" and "you don't have an audit trail of the exact image versions that you're using". 

This experiment was conducted independently of the proof-of-concept run reported in Section 4.1.2, using the same before and after images. The two sets of figures coincide to the byte because ubuntu:latest still resolved to the same manifest on the second occasion and the measurement pipeline is deterministic. That agreement confirms the determinism of the measurement rather than the stability of the refactoring: it holds only for as long as the publisher leaves the tag pointing where it is. 

#### **R03 — Add ENV Variable** 

**Performance X.** The controlled experiment on alpine:3.20, pinned by digest in both states, measured an increase of 174 bytes (3,632,570 → 3,632,744), corresponding to the manifest entry for the ENV directive. The Docker Documentation [7] states that "each ENV line creates a new intermediate layer, just like RUN commands", and the measurement quantifies that layer as metadata carrying no filesystem content. Under the relevance threshold adopted in this work, 174 bytes represent 0.005% of the image and produce no measurable effect on storage, network transfer, or start-up time. 

**Security ↓.** Both the Docker Documentation [7] and Bui et al. [28] warn that placing sensitive data in ENV instructions is a security risk. Bui et al. observe that such values are "transferred to the Docker images during the build and visible to every image user", and the documentation adds the mechanism: "even if you unset the environment variable in a future layer, it still persists in this layer and its value can be dumped." This risk is strictly conditional on the nature of the centralised value. As Rahman and Williams [29] establish for infrastructure-as-code more generally, a security smell is a recurring coding pattern that implies a security weakness, but labelling that pattern an actual vulnerability "necessitates consideration of the application context": a hard-coded secret is relevant only if it is genuinely used to authenticate. Where the refactoring targets operational data such as software versions or directory paths, no security risk materialises. 

**Maintainability ↑.** The Docker Documentation [7] recommends ENV "to set commonly used version numbers so that version bumps are easier to maintain", noting that this approach "lets you change a single ENV instruction to automatically bump the version of the software in your container". Nüst et al. [16] make the same point, observing that ENV is useful for setting software versions or paths and reusing them across multiple instructions to avoid mistakes. 

#### **R04 — Add ARG Instruction** 

**Performance X.** The controlled experiment on alpine:3.20 measured an increase of 193 bytes (3,632,570 → 3,632,763). Read against R03, the pair establishes an empirical contrast that the literature had asserted but not quantified: the ARG directive costs 19 bytes more than the equivalent ENV, consistent with the documentation's statement that build arguments "may persist in the image metadata, as provenance attestations and in the image history", the provenance record being the additional overhead. Both values are manifest metadata rather than filesystem content, and both fall below the relevance threshold. 

**Security ↓.** The Docker Documentation [7] states that build arguments "are inappropriate for passing secrets to your build, because they're exposed in the final image", and that they "may persist in the image metadata, as provenance attestations and in the image history, which is why they're not suitable for holding secrets". As with R03, the risk is conditional on whether the centralised value is a credential or operational metadata. 

**Maintainability ↑.** The Docker Documentation [7] states that specifying versions as build arguments "lets you build with different versions without having to manually update the Dockerfile" and that "it also makes it easier to maintain the Dockerfile, since it lets you declare versions at the top of the file", concluding that build arguments "make Dockerfiles more flexible, and easier to maintain". 

#### **R05 — Extract Stage** 

**Performance ↑.** Ksontini et al. [2] classify Extract Stage under the Image Size category, observing it in seven commits, the second most frequent of the five refactorings in that category. The Docker Documentation [7] gives the mechanism: multi-stage builds "let you reduce the size of your final image, by creating a cleaner separation between the building of your image and the final output", ensuring that "the resulting output only contains the files that are needed to run the application". 

**Security ↑.** This is the most pronounced security effect measured in the catalogue. The controlled experiment moved a Rust application from a single-stage rust:1.78 build to a multi-stage build with an alpine:3.20 runtime, reducing the vulnerability count from 6,162 to 0 (ΔCVEs = −6,162). The result confirms empirically what the Docker Documentation [7] recommends: "A small image with minimal dependencies can considerably lower the attack surface." Discarding the compiler toolchain and build dependencies from the final artifact eliminates the vulnerabilities they carry. 

**Maintainability ↑.** Ksontini et al. [2] classify this refactoring under Modularity, describing it as a case where "refactorings are used to reduce image complexity by breaking image into various stages". The same source characterises the absence of modularity as a condition where "adding new/changing existing components is difficult and error-prone", which is the defining concern of maintainability. 

#### **R06 — Inline Stage** 

**Performance X.** The controlled experiment on alpine:3.20 measured an increase of 116 bytes (3,632,710 → 3,632,826), attributable to layer metadata. The transformation removes a stage boundary without altering the filesystem content of the final image, and the residual variation falls below the relevance threshold. 

**Security X.** The vulnerability count was zero in both states (0 → 0). Because the alpine:3.20 baseline is itself null, this value does not distinguish an absence of effect from an absence of detectable vulnerabilities. 

**Maintainability ↑.** The logical instruction count fell by three (8 → 5) as the redundant FROM and the COPY --from were removed, collapsing the build from two stages into one. No rule in the 47-rule maintainability screen changed state. The reduction is a direct, measured structural simplification. 

#### **R07 — Sort Instructions** 

**Performance ↑.** Zhu et al. [30] evaluated instruction reordering across 2,000 GitHub repositories, reporting that the technique improved 92.75% of the Dockerfiles analysed, with a mean rebuild-time reduction of 26.5% and reductions above 50% in 12.82% of the files. The mechanism is postponing frequently modified instructions and prioritising stable, resource-intensive steps, which preserves cache validity across rebuilds. 

**Security X.** The controlled experiment on debian:12-slim measured a stable vulnerability count of 119 in both states (ΔCVEs = 0). With a non-null baseline, this is a measurement: reordering instructions changes when each step executes but not what the resulting image contains. 

**Maintainability ↓.** The same study reports that restoring semantic grouping, the arrangement developers find readable, carries a cost that Zhu et al. [30] quantify at approximately 5.9% and describe as a "trade-off between efficiency and readability". Optimal cache ordering and human-readable ordering are therefore not the same arrangement. 

#### **R08 — Replace ADD with COPY** 

**Performance X.** The controlled experiment on alpine:3.20 measured an increase of 1 byte (3,632,098 → 3,632,099), a nominal difference in the instruction configuration. For a regular local file, COPY and ADD produce identical content in the destination layer, and the variation is far below the relevance threshold. 

**Security ↑.** Bui et al. [28] identify the unnecessary use of ADD as a security smell, observing that "ADD instructions can download and unpack remote files from URLs without any checks, which potentially introduces security risks", and recommending replacement by equivalent COPY instructions. Replacing ADD where its extraction and fetching capabilities are not required removes that implicit behaviour. 

**Maintainability ↑.** Rosa et al. [17] report a 71% acceptance rate for DL3020 fixes submitted as pull requests, the second highest in their study. Ksontini et al. [2] list Replace ADD Instruction with COPY Instruction among the "three extra Dockerfile-related refactoring types performed to improve Maintainability", observing it in four commits, and attribute the benefit to ADD's unpredictability: "the result of such unreliable behavior often came down to copying when we want to extract and extracting when we want to copy." 

#### **R09 — Extract RUN Instructions** 

**Performance X.** The controlled experiment on alpine:3.20 measured an increase of 417 bytes (3,633,775 → 3,634,192), the largest residual variation in the catalogue, determined by the external script file added to the image and the manifest cost of the additional COPY 

directive. Although the most pronounced of the metadata-scale results, it remains three orders of magnitude below the operational threshold and is therefore classified as neutral. 

**Security X.** The vulnerability count was zero in both states (0 → 0). Because the alpine:3.20 baseline is itself null, this value does not distinguish an absence of effect from an absence of detectable vulnerabilities. 

**Maintainability ↑.** The controlled experiment measured a logical instruction count rising by one (5 → 6), reflecting the COPY added for the external script, with no rule in the 47-rule maintainability screen changing state. This positive delta is the structural cost of the extraction rather than a regression: the seven chained shell commands moved out of the Dockerfile were never counted, having lived inside the arguments of a single RUN, so the benefit of the operation falls outside the reach of the instruction count. The direction of that benefit is established by Ksontini et al. [2], who list Extract RUN Instructions among the "three extra Dockerfile-related refactoring types performed to improve Maintainability" and observe that the technique "does not only shrinks the image size but also groups commands in a much more cleaner, simpler, and portable format". The classification therefore combines the measured structural cost with the documented benefit that the metric cannot capture. 

#### **R10 — Update Base Image** 

**Performance ↑.** Haque and Babar [31] demonstrate the effect directly: replacing node:current-slim with node:alpine in a containerised application reduced the image from 183 MB to 127 MB — a variation well above the relevance threshold. Ksontini et al. [2] classify Update Base Image under the Image Size category, with twelve commits, the highest frequency of that category. 

**Security ↑.** Haque and Babar [31] report that in the same application 94.2% of the vulnerabilities in the final image were inherited from the base image, and that the substitution reduced the vulnerability count from 69 to 4. In a second demonstration, migrating from debian:jessie to debian:buster reduced highly exploitable and high impact vulnerabilities by 88.2%. The choice of base image therefore governs the majority of an application's vulnerability exposure. 

**Maintainability ↑.** Ksontini et al. [2] list Update Base Image among the "three extra Dockerfile-related refactoring types performed to improve Maintainability", explaining that using existing images avoids building and downloading dependencies on top of the base image, which "will reduce maintainability efforts as all required installations are done and best practices are probably applied especially when using official images". 

#### **R11 — Move Stage** 

Ksontini et al. [32] omitted this refactoring from their study because it appeared in only two Dockerfiles, so no measurement of its impact exists in the literature. Its effect was characterised exclusively through a controlled experiment on alpine:3.20, pinned by digest in both states. 

**Performance X.** The controlled experiment on alpine:3.20 measured an increase of 1 byte on the final runtime image (3,632,724 → 3,632,725). This is the only refactoring in the catalogue whose after state spans two files, so the image metrics are taken on the final runtime image alone: the builder is built first and consumed by tag, and since the two 

images share layers, their sizes are never summed. The residual variation falls below the relevance threshold. 

**Security X.** The vulnerability count was zero on the final runtime image in both states (0 → 0). Because the alpine:3.20 baseline is itself null, this value does not distinguish an absence of effect from an absence of detectable vulnerabilities. 

**Maintainability ↑.** The logical instruction count admits two readings. Counted across both after files it rises by one (8 → 9), since the extracted Dockerfile requires its own FROM; counted in the main Dockerfile alone it falls by three. Both are true: the first expresses the cost of the modularisation, the second what it relieves in the principal artifact. The classification follows the measured reduction of three instructions in the principal artifact. No rule in the 47-rule maintainability screen changed state across either file. 

#### **R12 — Remove RUN Instruction (mv command)** 

In the absence of an empirical study isolating this refactoring, its impact was measured exclusively through a controlled experiment on alpine:3.20, pinned by digest in both states. 

**Performance X.** The experiment measured a reduction of 1,331 bytes (3,634,927 → 3,633,596) through the elimination of two redundant layers. The direction of the effect is favourable, but the magnitude falls below the relevance threshold adopted in this work: at 1.3 KB the variation is three orders of magnitude below the operational scale of the artifact and produces no measurable effect on storage, network transfer, or start-up time. The dimension is therefore classified as neutral. The reduction is expected to scale with the size of the moved data, since that data would otherwise be duplicated across the temporary and final layers, but larger cases were not measured. 

**Security X.** The vulnerability count was zero in both states (0 → 0). Because the alpine:3.20 baseline is itself null, this value does not distinguish an absence of effect from an absence of detectable vulnerabilities. 

**Maintainability ↑.** The logical instruction count fell by two (8 → 6) as the two RUN instructions whose sole purpose was to execute a move were eliminated, with the destination path set directly in the preceding COPY instructions. No rule in the 47-rule maintainability screen changed state. 

#### **R13 — Update RUN Instruction** 

**Performance X.** The controlled experiment on alpine:3.20 measured an increase of 16 bytes (11,100,915 → 11,100,931), reflecting the longer command string stored in the image configuration after the instruction is split across lines. The package set and its versions are identical in both states, and the variation is negligible against an image of eleven megabytes, falling well below the relevance threshold. 

**Security X.** The controlled experiment on debian:12-slim measured a stable vulnerability count of 146 in both states (ΔCVEs = 0). With a non-null baseline this is a measurement: reformatting an instruction changes its physical layout without altering what is installed. 

**Maintainability ↑.** The Docker Documentation [7] recommends both components of this refactoring. On line splitting: "Split long or complex RUN statements on multiple lines 

separated with backslashes to make your Dockerfile more readable, understandable, and maintainable." On argument ordering: "Whenever possible, sort multi-line arguments alphanumerically to make maintenance easier. This helps to avoid duplication of packages and make the list much easier to update." Nüst et al. [16] concur, noting that "content spread across more and shorter lines also improves readability of changes in version control systems" 

#### **R14 — Rename Image** 

**Performance X.** The controlled experiment on alpine:3.20 measured no change whatsoever (3,632,095 → 3,632,095, ΔSize = 0). This is the only refactoring in the catalogue with an exact null size delta: assigning explicit names to build stages alters how they are referenced without adding any directive to the image manifest. The classification follows from the measurement itself and does not depend on the relevance threshold. 

**Security X.** The controlled experiment on debian:12-slim measured a stable vulnerability count of 77 in both states (ΔCVEs = 0). With a non-null baseline this is a measurement rather than an absence of data. 

**Maintainability ↑.** Ksontini et al. [2] classify renaming under Understandability, describing this category as refactorings "applied to reduce the effort to understand code, e.g., renaming elements". Replacing numeric stage indices with readable identifiers is the Dockerfile instance of that practice. The improvement is qualitative and outside the reach of the four quantitative indicators, which is reported as a genuine finding rather than a gap. 

#### **Baseline asymmetry in the security dimension** 

The security experiments for R06, R09, R11, and R12 were conducted on a clean alpine:3.20 baseline, yielding a constant zero count (0 → 0). 

Because these refactorings are purely structural and syntactic (modifying build stages or layer arrangements without altering software packages or dependencies), their security impact is inherently neutral. Even if evaluated on a non-null baseline (such as Debian), the resulting delta would remain zero, as structural transformations do not introduce or remove package vulnerabilities. The Alpine baseline thus correctly demonstrates the security safety and neutrality of these refactorings. 

The asymmetry runs the other way for the remaining security experiments. Inline RUN Instructions (R01), Sort Instructions (R07), Update RUN Instruction (R13), and Rename Image (R14) were measured on debian:12-slim rather than on alpine:3.20, and Extract Stage (R05) on the rust:1.78 toolchain image the refactoring itself requires. The reason is the one given above, applied in reverse: alpine:3.20 reports no vulnerabilities, so a ΔCVEs computed on it would be zero for every refactoring in the catalogue, and a zero obtained from a null baseline does not distinguish an absence of effect from an absence of anything to detect. On a baseline carrying a substantial and stable count, 146 for R01 and R13, 119 for R07, and 77 for R14, a null delta becomes a measurement in its own right, and the pronounced reduction recorded for R05 becomes attributable to the transformation rather than to the choice of image. 

### Classification Criteria 

Each refactoring is evaluated independently across all three quality axes, Performance, Security, and Maintainability, forming a complete three-dimensional impact vector. This 

approach provides a transparent overview of positive effects, neutral behaviors, and trade-offs introduced by each transformation across all axes without relying on a primaryversus-secondary hierarchy. 

Two rules govern how each axis is filled. First, a direction is only recorded when it is supported by evidence, whether measured in the literature or observed in a controlled experiment; no axis is marked to suggest importance where no supporting effect exists. Second, the value recorded on each axis carries a sign: an upward arrow marks an improvement, a downward arrow marks a regression, and a cross marks a neutral outcome, meaning that the refactoring leaves that axis unaffected or that the measured variation falls below the operational threshold defined for the dimension. 

Recording regressions directly in the columns rather than only in the surrounding text is what makes the vector complete. For example, Add ENV Variable (R03) and Add ARG Instruction (R04) improve maintainability, but both open the possibility of exposing sensitive data through the build, so security is recorded as a regression on those rows and explained in the justification below. In the same way, the readability cost of aggressive consolidation in Inline RUN Instructions (R01) and of reordering in Sort Instructions (R07) is recorded as a maintainability regression rather than left implicit. For Update Base Image (R10), moving to a lighter and more current base image reduces inherited vulnerabilities and shrinks the final artifact at the same time, so security and performance are both recorded as improvements, with neither presented as the consequence of the other. Read row by row, the table therefore answers three separate questions, what does this refactoring do to performance, to security, and to maintainability, instead of a single question about which dimension matters most. 

### Maintainability Established by the Nature of the Operation 

Refactorings such as R06 ($\Delta\text{Instr} = -3$), R09 ($\Delta\text{Instr} = +1$), R11 ($ \Delta\text{Instr} = +1$), and R12 ($\Delta\text{Instr} = -2$) are classified under maintainability as they exhibit distinct adjustments in the logical instruction count. These structural shifts occur by design: operations like stage extraction and modularization naturally introduce an intentional structural overhead, a necessary operational cost to establish multi-stage boundaries and context isolation, whereas inlining or removal actions reduce instruction counts. 

Maintainability, in terms of structural simplicity and readability, cannot be fully captured by standard artifact metrics. Through the analytical evaluation of the code's structure before and after the operation, we conclude that maintainability is enhanced, regardless of whether the instruction delta is positive or negative. For operations that increase instruction counts, this intentional addition is fully justified as the operational cost required to achieve direct gains in clarity, readability, and modular architecture, ultimately improving maintainability while preserving the integrity of the build process. 

### Distribution of the Catalogue 

The high prevalence of positive Maintainability ($\uparrow$) impacts across the catalogue reflects the structural nature of these refactoring operations rather than a classification bias. Both empirical data and existing literature confirm that the catalogued transformations, such as stage naming, instruction formatting, variable extraction, and logic modularization, systematically target and enhance Dockerfile readability and organization. Where a refactoring produces direct benefits in Performance ($\uparrow$) or Security ($\uparrow$), the three-dimensional vector explicitly records it: Inline RUN Instructions (R01), Extract Stage (R05), and Sort Instructions (R07) deliver measurable Performance improvements, while Extract Stage (R05), Replace ADD with COPY (R08), 

and Update Base Image (R10) actively enhance Security. Consequently, the classification vector for each rule follows individual empirical and theoretical evidence, rather than an artificial target balance across the three dimensions. 

## VCS Connector 

### Technical Description 

The VCS Connector is the entry point of the analysis pipeline. Its sole responsibility is to retrieve the complete textual content of the Dockerfile at each of the two specified commits, making it available to the Detection Engine as a UTF-8 string. The component interacts exclusively with the Git object model through GitPython, without modifying the repository state or writing any files to the filesystem. 

Given a commit SHA, GitPython resolves it to a git. Commit object, from which the commit's tree is accessed. The tree is navigated to the blob corresponding to the Dockerfile path, and its byte content is read through the data_stream interface and decoded to UTF-8. This sequence of operations is idempotent: repeated calls with the same commit SHA always return identical strings, satisfying RNF5. 

Table 4.4 compares the two access strategies considered for the VCS Connector: 

#### **VCS Connector** 

|**Approach**|**Reproducible**|**Validated**|
|---|---|---|
|**Shell git show**|❌Shell escaping artefacts|❌|
|**GitPython (selected)**|❌Programmatic blob access|❌Experiment 3|



Table Design.4 - Version control system access methods considered for the VCS Connector 

GitPython was selected over higher-level mining frameworks because the VCS Connector's task is narrow: retrieving the Dockerfile at two known commits. For this, GitPython's programmatic, blob-level access to file content at any commit, without a working-tree checkout, is sufficient and avoids the overhead of a full mining framework. Spadini et al. [33] characterise GitPython as the state-of-the-art Python framework for interacting with Git, and propose PyDriller as a more concise mining alternative; that alternative is unnecessary for this task. This access was validated in Experiment 3 against the docker/getting-started repository, satisfying RF1. 

### Design and Requirements 

#### **Planned Changes** 

In the current state of practice, accessing the Dockerfile at a historical commit requires manual invocation of git show <commit>:Dockerfile, followed by saving the output to a file 

for further processing. This workflow is error-prone, non-reproducible across shell environments, and unsuitable for automation. The VCS Connector replaces this workflow with a programmatic API call that returns the file content as a Python string directly, eliminating shell escaping artefacts and ensuring byte-identical retrieval. 

#### **Challenges** 

The principal challenge of this component is the handling of repositories where the Dockerfile is not located at the root of the repository tree, but within a subdirectory. The design accommodates this by accepting the Dockerfile path as a parameter rather than assuming a fixed location. A secondary challenge is the handling of commits where the Dockerfile did not yet exist; the component raises an informative exception in this case, allowing the pipeline to abort cleanly rather than producing an empty string that downstream components would misinterpret. 

#### **Functional and Non-Functional Requirements** 

The VCS Connector must satisfy RF1 fully: it must extract the Dockerfile content at both commits without requiring a working tree checkout. Non-functionally, it must satisfy RNF5 (reproducibility) by ensuring that the same commit SHA always yields the same output, and RNF4 (reliability) by raising specific exceptions for non-existent commits and nonexistent Dockerfile paths. 

#### **Design** 

The component is implemented as a stateless function that accepts the repository path, SHA_A, SHA_B, and an optional Dockerfile path (defaulting to the repository root). It returns a named tuple containing Dockerfile_A and Dockerfile_B as strings. The stateless design ensures that the component has no side effects and can be tested in isolation with any Git repository. 

## Detection Engine 

### Technical Description 

The Detection Engine is the analytical core of the pipeline. It receives the two Dockerfile strings from the VCS Connector and determines whether the structural change between them constitutes a recognised refactoring type. The engine uses dockerfile-parse to decompose each Dockerfile into an ordered list of logical instruction objects, each containing the instruction type and its normalised argument string, and then applies a set of detection rules, one per supported refactoring type. 

The prototype implements automated detection rules for all fourteen refactoring types of the extended catalogue presented in Section 4.2, since the catalogue is adopted in full rather than as a selected subset. 

Table 4.5 compares the two parsing strategies considered for the Detection Engine: 

#### **Detection Engine** 

|**Approach**|**Multi-line RUN**<br>**support**|**Python-native**|**Validated**|
|---|---|---|---|
|**Regex line matching**|❌|❌|❌|
|**dockerfle-parse**<br>**(selected)**|❌|❌|❌Experiment 5|



Table Design.5 - Dockerfile parsing strategies considered for the Detection Engine 

Regex-based line matching was rejected because Dockerfile instructions can span multiple physical lines through the backslash continuation character [7], preventing a line-level parser from reconstructing them into the canonical logical representations required by RF2. The adoption of structural parsing is consistent with the approach taken by DRMiner [9], which employs an Enhanced AST to capture the structural complexities of Dockerfile instructions. dockerfile-parse was selected and its ability to correctly reconstruct multi-line instructions was confirmed in Experiment 5, where four logical RUN instructions spread across multiple physical lines were correctly identified as four units, satisfying RF2. 

### Design and Requirements 

#### **Planned Changes** 

In the current state, the existence of a refactoring in a commit can only be identified through manual inspection of the diff, a process that Ksontini et al. [9] note is rarely documented by developers. The Detection Engine replaces manual inspection with automatic structural comparison, producing a typed result that names the refactoring and identifies the specific instructions involved. 

#### **Challenges** 

Beyond the multi-line parsing challenge resolved by dockerfile-parse (Section 4.1.3), the Detection Engine must resolve the consolidation-versus-deletion ambiguity described in Section 4.1.3. It also faces the challenge of concurrent rule activation: when a commit modifies the Dockerfile in a way that matches multiple detection rules simultaneously, the engine operates under a non-exclusion principle. In the prototype, rather than enforcing an arbitrary hierarchical filter that privileges one quality dimension over another, the system dynamically records all identified patterns into a cumulative sequence. This ensures that every applied optimization, whether targeting Security, Performance, or Maintainability, is fully captured and quantified. If a deterministic execution sequence is required by the programmatic pipeline, the engine relies strictly on the chronological order of the rule-registry index, completely decoupling the processing flow from any perceived severity of the quality dimensions. 

#### **Functional and Non-Functional Requirements** 

The Detection Engine must satisfy RF2: parse both Dockerfiles into logical representations and identify the refactoring type and affected instructions. It must satisfy RNF3 (extensibility) by implementing each rule as an independent function registered in a central rule registry, so that new types can be added without modifying existing rules. 

### Supported Refactoring Types 

Before listing the types the prototype supports, it helps to position each one against the tools reviewed in Section 3.4. Table 4.6 maps the fourteen refactorings to the Hadolint rule they address, where one exists, to the coverage provided by DRMiner, and to the implementation decision made for the prototype. Hadolint and DRMiner operate at different levels, so each column is read on its own terms: Hadolint reports individual smells on a single Dockerfile snapshot, while DRMiner is the only tool that detects refactorings across two revisions. The Hadolint column therefore names the smell a refactoring fixes, where one exists, rather than claiming Hadolint detects the refactoring itself. 

Only three refactorings map directly to specific Hadolint rules: Inline RUN Instructions (DL3059), Update Base Image TAG (DL3007), and Replace ADD with COPY (DL3020) [10]. This limited mapping is expected, as Hadolint validates best-practice compliance within static snapshots, whereas most refactoring operations involve deeper structural transformations that transcend standard linting. 

The Docker-Parfum column narrows this further. Although Docker-Parfum reimplements a subset of Hadolint rules, it imports only six of them, and of the three rules above only DL3020 is among that subset [22]. Replace ADD with COPY (R08) is therefore the single catalogue refactoring that Docker-Parfum both detects and repairs; for the remaining thirteen, no corresponding rule exists in its catalogue. This near-absence of overlap stems from a difference in the level at which each tool operates: Docker-Parfum targets smells located inside the arguments of shell commands, while the extended catalogue operates on the structure of the Dockerfile itself (the tag of a base image, the presence and arrangement of stages, the declaration of ENV and ARG variables, and the order of instructions) [22]. 

Regarding detection capabilities, DRMiner identifies twelve of the fourteen refactoring types through its Enhanced AST matching, with the remaining two, Remove RUN (mv command) and Update RUN Instruction, currently lacking automated coverage [9]. Nevertheless, the prototype implements detection rules for all fourteen types as they constitute the extended catalogue of common Dockerfile refactorings identified in the literature [2]. By implementing the complete set rather than a restricted subset, the prototype ensures that the catalogue’s classification is applied consistently to every detected refactoring, providing a comprehensive and standardized assessment framework. 

The prototype resolves the research gap identified in Chapter 3 regarding existing tools such as DRMiner [9]: the lack of automated coverage for the complete set of common Dockerfile refactorings. By implementing detection rules for all fourteen types of the extended catalogue, the tool identifies these refactorings and provides an evaluation of the Dockerfile across quality dimensions such as performance, security, and maintainability. 

|**ID**|**Refactoring**<br>**Type**|**Hadolint**<br>**(smell**<br>**fxed)**[10]|**DRMiner**<br>[9]|**Docker-**<br>**Parfum**<br>[22]|**Implemented**<br>**in Prototype**|
|---|---|---|---|---|---|
|**R01**|Inline RUN<br>Instructions|DL3059|Yes|No|Yes|
|**R02**|Update Base<br>Image TAG|DL3007|Yes|No|Yes|
|**R03**|Add ENV<br>Variable|—|Yes|No|Yes|
|**R04**|Add ARG<br>Instruction|—|Yes|No|Yes|
|**R05**|Extract Stage|—|Yes|No|Yes|
|**R06**|Inline Stage|—|Yes|No|Yes|
|**R07**|Sort<br>Instructions|—|Yes|No|Yes|
|**R08**|Replace ADD<br>with COPY|DL3020|Yes|Yes|Yes|
|**R09**|Extract RUN<br>Instructions|—|Yes|No|Yes|
|**R10**|Update Base<br>Image|—|Yes|No|Yes|
|**R11**|Move Stage|—|Yes|No|Yes|
|**R12**|Remove RUN<br>(mv<br>command)|—|No|No|Yes|
|**R13**|Update RUN|—|No|No|Yes|



|**ID**|**Refactoring**<br>**Type**|**Hadolint**<br>**(smell**<br>**fxed)**[10]|**DRMiner**<br>[9]|**Docker-**<br>**Parfum**<br>[22]|**Implemented**<br>**in Prototype**|
|---|---|---|---|---|---|
||Instruction|||||
|**R14**|Rename<br>Image|—|Yes|No|Yes|



Table Design.6 - Relationship between the fourteen catalogue refactorings and the reviewed tools (Hadolint reports smells; DRMiner detects refactorings), with the implementation decision for the prototype 

## Performance Analyzer 

### Technical Description 

To retrieve image metadata within the containerized environment, the two official interfaces provided by the ecosystem were considered: the command-line interface (Docker CLI) and the software development kit (Docker SDK). In strict respect to the official Docker Engine API architecture [34], these two approaches represent the standard interfaces available to send instructions and interact with the Docker daemon. However, during the architectural investigation of these methods, a critical limitation in the Docker CLI regarding image size precision was identified. As documented by the developer community in Docker Issue #31298 [35], the CLI introduces decimal rounding and humanreadable truncation (e.g., rounding byte counts to the nearest megabyte) by design. Since the non-functional requirement RNF1 demands byte-level precision to detect microvariations and small size deltas, any reliance on the CLI was rejected. 

Consequently, the Performance Analyzer measures the impact of the detected refactoring on the Performance dimension by building the Docker image from each Dockerfile state and communicating with the Docker daemon exclusively through the Docker SDK. It utilizes the image.attrs["Size"] attribute, which returns the VirtualSize, the total uncompressed byte count of all image layers, as a 64-bit integer. Experiment 4 confirmed that this direct query to the underlying API endpoint returns an exact byte count, 29,748,045 bytes (28.37 MB) for the documented public test image (ubuntu:22.04) used in that experiment, a precision level that would be rounded away by the CLI visual interface. 

Build time was considered as an additional performance metric but was excluded from the prototype design. Its high sensitivity to environmental factors, host hardware, Docker cache state, network latency, makes a single measurement per state insufficient for reliable delta computation. Image size, by contrast, is a deterministic function of the 

Dockerfile content and the base image state, producing the same byte count for the same inputs every time. 

Table 4.7 compares the two size retrieval methods considered for the Performance Analyzer: 

#### **Performance Analyzer:** 

|**Approach**|**Precision**|**Validated**|
|---|---|---|
|**Docker CLI (--format**|❌Rounded human-readable|❌Docker issue #31298|
|**"{{.Size}}")**|strings|[35]|
|**Docker SDK (selected)**|❌Raw 64-bit integer bytes|❌Experiment 4|



Table Design.7 - Image size retrieval methods considered for the Performance Analyzer 

The Docker CLI was rejected because it returns human-readable strings that introduce rounding imprecision, a behavior documented in the Docker project's own issue tracker. This was confirmed in the context of this prototype in Experiment 4, where the Docker SDK returned an exact byte count for a test image (29,748,045 bytes) rather than a rounded string. This byte-level precision is what allows small deltas, such as the −194,991 bytes measured for the Inline RUN Instructions refactoring in PoC-1 — to be computed correctly, where CLI rounding would reduce them to zero and violate RNF1. 

### Design and Requirements 

#### **Planned Changes** 

While a standard pipeline design might measure image size using the Docker CLI command docker images --format "{{.Size}}", technical documentation and open issues (such as Docker issue #31298) indicate that this approach returns a pre-parsed, humanreadable string subject to rounding imprecision. To bypass this limitation from the start, the Performance Analyzer replaces any reliance on the CLI with a direct SDK call that returns the raw integer byte count, completely eliminating the human-readable truncation risk 

#### **Challenges** 

The Performance Analyzer requires the Docker daemon to be running on the host system and the image build to complete successfully for both states. Builds that fail, due to 

network errors during package installation or invalid Dockerfile syntax, must be handled gracefully, with the component raising an informative exception that allows the pipeline to abort cleanly and report the failure accurately. 

#### **Functional and Non-Functional Requirements** 

The component must satisfy RF4 (byte-precise size retrieval) and RNF1 (metric precision sufficient to detect significant size reductions), as demonstrated by Experiment 4, where the Docker SDK successfully retrieved the exact, unrounded count of 29,748,045 bytes for the ubuntu:22.04 test image, preventing the human-readable rounding and truncation errors inherent in the Docker CLI which would approximate this value to 29 MB. 

## Data Extractor 

### Technical Description 

The Data Extractor is responsible for collecting the Security and Maintainability metrics for both Dockerfile states. It invokes Hadolint [10] and Trivy [36] in parallel against each image state and normalises their heterogeneous JSON outputs into a common internal metric schema. The parallel execution is architecturally justified by the mutual independence of the two operations: Hadolint analyzes the Dockerfile text while Trivy scans the built image, and neither requires the result of the other. Running them concurrently reduces the total metric collection time to approximately the duration of the slower operation. 

#### **Table 4.8 compares the two invocation strategies considered for the Data Extractor:** 

**Data Extractor** 

|**Approach**|**Total time**|**Validated**|
|---|---|---|
|**Sequential invocation**|❌Sum of both execution times|❌|
|**Parallel invocation (selected)**|❌Duration of the slower operation|❌Bass et al.[37]|



Table Design.8 - Tool invocation strategies considered for the Data Extractor. 

Sequential invocation was rejected because it introduces unnecessary blocked time when two mutually independent operations run one after the other — a suboptimal design that Bass et al. identify as the precondition for applying the 'Introduce Concurrency' performance tactic [37]. Hadolint and Trivy satisfy this precondition: Hadolint performs static analysis on the Dockerfile text while Trivy scans the built image, meaning neither tool requires the output of the other as input. Parallel invocation was therefore selected, reducing total metric collection time from the sum of both execution times to the duration of the slower operation [37]. 

Both tools are executed as Docker containers rather than as locally installed binaries, using their official images (hadolint/hadolint and aquasec/trivy). This keeps the tool versions pinned and reproducible across environments and avoids host-level installation dependencies. The prototype invokes each container through the Docker daemon: Hadolint receives the Dockerfile text via standard input, while Trivy is given access to the built image to be scanned. 

During data extraction, the tool executes external static analysis and security tools, collecting their raw report outputs in JSON format. While these raw artifacts are processed internally for metric extraction, they are optionally preserved for auditability and reproducibility purposes, enabling full transparency of the underlying analysis 

#### **Functional and Non-Functional Requirements** 

The Data Extractor must satisfy RF5: invoke both tools in JSON mode, normalise their schemas, and return warning and CVE count deltas. It must satisfy RNF2 (sensitivity to the complete elimination of relevant Hadolint rule violations), RNF4 (reliability through exception handling), and RNF5 (reproducibility through Trivy database version recording). 

### Security Metrics — Trivy 

Trivy is invoked in image-scanning mode with the --format json flag. The component navigates the resulting Results[].Vulnerabilities[] structure and counts occurrences by severity tier (CRITICAL, HIGH, MEDIUM, LOW, UNKNOWN), producing a dictionary that represents the security profile of each image state. Experiment 2 confirmed the stability of this schema. The PoC-3 proof-of-concept experiment confirmed Trivy's diagnostic sensitivity: it correctly identified the vulnerabilities present in the ubuntu:22.04 base image and the smaller set present in the minimal alpine:3.19 image, capturing a Delta CVEs of -15 and demonstrating that the choice of base image is a primary driver of an image's security profile. 

Trivy was selected as the security instrument because it is the most widely adopted opensource container vulnerability scanner, used as the default in projects such as Harbor and certified by Red Hat [36]. Alternatives such as Grype exist, but Trivy was chosen for its broader coverage across OS and language packages. 

### Maintainability Metrics — Hadolint 

Hadolint [10] is invoked via standard input pipe with the --format json flag. The component parses the resulting flat array of warning objects and applies the maintainability screen defined in Section 4.1.3, retaining the 47 default-enabled Hadolint and ShellCheck rules that target maintainability and discarding those whose effect belongs to the performance or security dimensions, since those effects are already measured by ΔSize and ΔCVEs. The screen is held in a single declarative rule list, so it can be inspected and revised without touching the parsing logic. For the proof-of-concept runs of Section 4.1.2 the list is bypassed and the raw total is recorded instead, in line with the two-regime distinction stated in Section 4.1.3. 

It is explicitly acknowledged that Hadolint functions as a proxy for maintainability rather than a direct measurement thereof, as its rules encode conformance to documented best 

practices [7] rather than the full range of maintainability characteristics. This operationalisation is consistent with Wu et al. [8], who used Hadolint-detected smells as empirical indicators of Dockerfile quality issues. It is also why Hadolint is not the only maintainability indicator: as described in Section 4.1.3, the warning count is complemented by the logical instruction count (ΔInstr), which reports structural change at a level the rule set does not reach. The two are collected by the same component, the Data Extractor, and are reported side by side: Hadolint through an external invocation, ΔInstr through a direct count over the parsed instruction list.. This limitation is declared in Section 4.9. 

Hadolint was selected as the maintainability instrument because it is the reference tool used in the literature for detecting Dockerfile smells, adopted both in empirical studies and in enterprise code quality tooling [17]. 

### Maintainability Metrics — Logical Instruction Count 

The second maintainability indicator requires no external tool. The component parses each Dockerfile state with dockerfile-parse, the same library used by the Detection Engine, and counts the resulting logical instructions, excluding COMMENT entries, which the parser reports alongside instructions but which are not instructions themselves. Because the parser reconstructs multi-line instructions into a single logical unit, a RUN split across several physical lines with backslash continuations counts as one, which is what makes the count insensitive to formatting. 

The count is returned for both states as part of the MetricSet, and the Report Generator computes the signed difference (ΔInstr) in the same way it computes the other deltas. The rationale for this indicator, and the reading its non-monotonic behavior requires, are set out in Section 4.1.3. 

## Report Generator 

### Technical Description 

The Report Generator is the terminal stage of the pipeline. It consumes the DetectionResult produced by the Detection Engine and the two MetricSet objects produced by the Performance Analyzer and the Data Extractor, computes the signed delta for each quality metric, and produces the ImpactReport. Its role is aggregation, not interpretation: it pairs the formal identifier of the detected refactoring with the four measured deltas exactly as they were obtained, and adds no expected direction, no dimensional label, and no judgement about whether the result matches the catalogue. 

The sign convention is uniform for the three metrics that measure the built image and the smell count: a negative delta indicates improvement (smaller image, fewer CVEs, fewer warnings). The sign convention is uniform for the three metrics that measure the built image and the smell count: a negative delta indicates improvement (smaller image, fewer CVEs, fewer warnings). For Security, the report includes a net-change per-severity delta vector rather than a single aggregate, enabling detection of cases where the total CVE count improves but the severity distribution worsens 

_Δ_ Instr is reported under a contextual reading rather than as a scalar regression indicator. As set out in Section 4.1.3, refactorings act on the instruction count in opposite directions by design: consolidation and removal reduce it, whereas extraction and addition increase it. Consequently, a positive _Δ_ Instr is not inherently interpreted as a quality degradation. The report presents _Δ_ Instr alongside the specific refactoring type that produced it, ensuring the metric is evaluated against the nature of the applied operation rather than against an arbitrary fixed target. 

Table 4.9 compares the two output formats considered for the Report Generator: 

#### **Report Generator** 

|**Approach**|**Structured output**|**Validated**|
|---|---|---|
|**Plain text**|❌|❌|
|**JSON (selected)**|❌|❌RFC 8259[38]|



Table Design.9 - Output formats considered for the Report Generator. 

JSON was selected as the primary output format instead of unstructured alternatives (e.g., plain text), because it is a standardised lightweight format designed specifically for the portable representation of structured data [38], satisfying RF7, which requires structured output for programmatic processing, and RNF5, which requires identifiable fields for the analysis timestamp. 

#### **Functional and Non-Functional Requirements** 

The Report Generator must satisfy RF7: produce a structured output presenting beforeand-after values along with the computed metric deltas. The report is serialised in JSON format for downstream processing and in a human-readable text summary for direct review by practitioners. Both formats include the analysis timestamp and the commit SHAs to satisfy RNF5 (reproducibility). 

## System Data Flow 

This section traces the complete data flow of the system from user inputs to the final ImpactReport, identifying the typed data structures exchanged at each component boundary. 

Table 4.10 summarises the typed data transformations at each pipeline stage: 

|**Stage**|**Components**|**Data Transformation**|
|---|---|---|
|**1**|VCS Connector|Input: Repository/SHA. Output: Dockerfle<br>text.|
|**2**|Detection Engine|Input: Dockerfles. Output: DetectionResult.|
|**3**|Performance Analyzer,<br>Data Extractor|Input: Dockerfles. Output: Metrics<br>(MetricSet) / Deltas.|
|**4**|Report Generator|Input: DetectionResult + MetricSet. Output:<br>ImpactReport (JSON).|



Table Design.10 - Data transformations at each pipeline stage. 

## Design Limitations and Mitigations 

The prototype implements all fourteen refactoring types catalogued by Ksontini et al. [2]. Four of them were exercised in isolated proof-of-concept experiments to establish the measurement baselines; the empirical evaluation of the full set is addressed in Chapter 6. 

The four refactoring types exercised in the proof-of-concept experiments, Inline RUN Instructions, Update Base Image TAG, Update Base Image, and Replace ADD with COPY, were selected as representative cases of the quality dimension profiles supported by the catalogue. Together they exercise the performance, security, and maintainability dimensions, providing empirical evidence that the three-axis measurement principle holds across distinct refactoring profiles, including refactorings that affect a single dimension and refactorings that affect more than one. 

The empirical feasibility of each selected type was validated through four isolated proofof-concept experiments, one per type, producing concrete baseline values for each delta metric. These baselines are documented in Section 4.1.2 and serve as acceptance criteria for the verification strategy described in Section 4.1.6. 

The consolidation-versus-deletion ambiguity described in Section 4.1.3 is mitigated by the content preservation check but not fully resolved. Commits where both consolidation and deletion occur simultaneously produce a mixed-change result that is explicitly flagged in the report as requiring human validation. This limitation is shared with DRMiner [9], which also cannot deterministically resolve this class of ambiguity. 

Build time is excluded from the Performance dimension due to its high environmental sensitivity, as discussed in Section 4.5.1. The Performance dimension is therefore operationalised exclusively through image size. Incorporating build time in a statistically 

reliable way would require multiple measurements per state and a controlled environment; this is identified as a direction for future work. 

The use of Hadolint [10] as a proxy for maintainability is a methodological simplification consistent with Wu et al. [8] and Rosa et al. [17], and declared as a threat to validity in Chapter 6. The addition of ΔInstr reduces, but does not remove, the exposure of the maintainability dimension to that simplification. Three limitations of the structural indicator are acknowledged. First, it measures structure and not maintainability itself: fewer instructions indicate a simpler Dockerfile, following the use of instruction count as a complexity proxy by Wu et al. [8], but simplicity and maintainability are related rather than equivalent. Second, it is not monotonic, so its sign cannot be interpreted without knowing which refactoring produced it. Third, it is blind to refactorings that leave the instruction count unchanged, which is the case for Sort Instructions (R07), Update RUN Instruction (R13), and Rename Image (R14); for the last two, no metric adopted here registers their effect, and the maintainability classification rests on the nature of the operation as discussed in Section 4.2.3. 

The prototype requires a locally running Docker daemon and a pre-cloned repository as operational pre-conditions. It does not include a graphical interface, batch processing, or CI/CD integration. These capabilities are identified as future work in Chapter 7. 

The prototype’s measurement scope is strictly bound to the Dockerfile path specified for the tracked artifact (RF1). Restricting the tracking scope to a single file path constitutes a deliberate design decision aimed at ensuring a strictly deterministic measurement pipeline, avoiding speculative heuristics that would be necessary for the automatic aggregation of satellite files (e.g., Dockerfile.builder). While this approach covers the vast majority of the case studies (14 out of 15 scenarios), structural multi-file refactorings fall outside the current functional scope. As observed in the experiments, this design is transparent: while refactorings like R09 (Extract RUN) show no divergence because they offload logic to shell scripts (which do not count as Dockerfile instructions), refactorings like R11 (Move Stage) diverge from global catalog accounting in instruction count ( _Δ_ Instr) because they create a new, separate Dockerfile. This limitation is consciously assumed to safeguard the internal validity of the impact analysis, representing a structural property of the prototype's scope, which audits the primary artifact’s evolution rather than calculating total project state changes, and relegating support for multi-file repositories to future research directions. 

Furthermore, a key methodological disclaimer acknowledged in this design framework concerns the contextual and volatile nature of external container environments during local dynamic assessment. While the extended catalogue (Section 4.2) maps the theoretical quality directions expected from each refactoring type based on empirical literature, the experimental deltas derived from real-world execution remain inherently dependent on operational context. 

External variables entirely decoupled from the Dockerfile's syntax—such as transient network latency during RUN instructions, untracked updates within remote package manager mirrors (e.g., unexpected software upgrades during an apt-get execution), or 

silent baseline adjustments in external images maintained by public registries—can introduce confounding factors that temporarily perturb the collected performance ($ \Delta$Size) and security ($\Delta$CVEs) indicators. 

Consequently, the central validation criterion for the prototype's effectiveness rests on its structural detection accuracy. Localized deviations or anomalies within empirical quality deltas do not compromise the system's precision; instead, they are evaluated as valuable reflections of Infrastructure-as-Code ecosystem volatility, highlighting critical real-world edge cases where theoretically sound refactoring patterns encounter conflicting practical outcomes. 

## Summary 

This chapter presented the complete design of the prototype tool for automated Dockerfile refactoring detection and multi-dimensional quality impact assessment. The architecture is a sequential data pipeline of five components, VCS Connector, Detection Engine, Performance Analyzer, Data Extractor, and Report Generator, each with a clearly bounded responsibility, a typed interface, and a directly traceable validation experiment. 

The VCS Connector design is grounded in Experiment 3 (GitPython, commits 2bca273 and 2981665, docker/getting-started). The Detection Engine design is grounded in Experiment 5 (dockerfile-parse, 4-to-1 RUN consolidation detected automatically). The Performance Analyzer design is grounded in Experiment 4 (Docker SDK, 29,748,045 bytes retrieved via daemon API). The Data Extractor design is grounded in Experiment 2 (Hadolint and Trivy JSON schemas validated). 

The central contribution of the design is the introduction of the delta (Delta) as the analytical unit of quality communication. The four isolated proof-of-concept experiments demonstrated that the supported refactoring types produce measurable and distinct values across the four deltas and the three quality dimensions they operationalise, with different refactorings affecting different combinations of those dimensions. Inline RUN Instructions produced Delta Size = −194,991 bytes, ΔWarnings (total raw) = −7 and Delta Instr = −3, confirming both the complete elimination of the consecutive-RUN smell and the structural consolidation that produced it. Update Base Image TAG produced Delta Warnings(DL3007) = −1, eliminating the latest-tag smell. Update Base Image produced Delta Size = −26,318,550 bytes and Delta CVEs = −15, showing that the choice of base image moves performance and security simultaneously. Replace ADD with COPY produced Delta Warnings(DL3020) = −1 with negligible size and no security impact. Across this set, the evaluated refactorings produced clear, measurable changes in their respective dimensions without introducing unexpected cross-dimensional conflicts. The prototype automates the measurement of these deltas between commits, addressing the inability of existing tools to objectively quantify the actual impact of detected refactorings. The following chapter describes how this design was realised in code. 

