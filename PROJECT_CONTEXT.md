# Project Context — Master's Dissertation Prototype
# "Dockerfile Refactorings: Detection and Effects" (ISEP)

## Goal
A Python 3 tool that receives a Git repository path and two commit identifiers, extracts the Dockerfile at each commit from version history, detects whether a structural refactoring occurred between them, and produces an impact report quantifying the changes across four metrics (ΔSize, ΔCVEs, ΔWarnings, and ΔInstr)[cite: 3].

## Input / Output
- INPUT: a Git repository path + two commit SHAs (with optional subdirectory support)[cite: 3].
- OUTPUT: an impact report (JSON format, RFC 8259) + a human-readable text summary detailing the detected refactoring type, metrics, and trade-off flags[cite: 3].

## Pipeline (FIXED)
VCS Connector → Detection Engine → [Performance Analyzer + Data Extractor (Parallel Execution)] → Report Generator[cite: 3]

## Metrics Measured (FIXED — build time excluded due to high sensitivity to environmental factors)
- **Image Size ($\Delta\text{Size}$)** → Performance: retrieved in bytes via the Docker SDK using `image.attrs["Size"]` (exact uncompressed VirtualSize byte count via 64-bit integer)[cite: 3].
- **Hadolint Warnings ($\Delta\text{Warnings}$)** → Maintainability: filtered strictly by a maintainability screen of 47 rules (retaining default-enabled rules related to code structure, notation, metadata, build logs, and shell correctness, while excluding performance and security rules)[cite: 3].
- **CVE Count ($\Delta\text{CVEs}$)** → Security: structured vulnerability count vector by severity tier using Trivy JSON output[cite: 3].
- **Logical Instruction Count ($\Delta\text{Instr}$)** → Maintainability: direct structural count derived from the textual content of the Dockerfile via `dockerfile-parse`[cite: 3].

## Components, Technologies and Responsibilities (FIXED)
- **VCS Connector** — GitPython. Navigates the Git object model natively. Retrieves the Dockerfile content at any commit as a UTF-8 string WITHOUT a working-tree checkout or filesystem writes. Raises explicit exceptions for missing files or commits[cite: 3].
- **Detection Engine** — `dockerfile-parse`. Reconstructs multi-line RUN instructions (backslash continuation) into their logical single-unit form BEFORE detection to prevent false instruction counts. Detects all 14 refactoring types (R01–R14)[cite: 3]. Uses a fusion-proof criterion to resolve consolidation-versus-deletion ambiguities. [cite: 3].
- **Performance Analyzer** — Docker SDK for Python. Builds images locally and extracts exact raw byte integers using `image.attrs["Size"]`, avoiding CLI rounding imprecision. Computes a signed delta ($\Delta\text{Size}$)[cite: 3].
- **Data Extractor** — Runs Hadolint and Trivy concurrently in Docker containers (`hadolint/hadolint` and `aquasec/trivy`) to minimize execution time[cite: 3]. Normalizes their heterogeneous JSON schemas and invokes `dockerfile-parse` independently to extract the logical instruction count from the textual content of the Dockerfile[cite: 3].
- **Report Generator** — Consumes outputs, computes signed deltas ($\Delta\text{Size}$, $\Delta\text{CVEs}$, $\Delta\text{Warnings}$, $\Delta\text{Instr}$), and produces the final JSON impact report[cite: 3].

## The 14 Refactoring Types to Detect
- R01 Inline RUN Instructions[cite: 3]
- R02 Update Base Image TAG[cite: 3]
- R03 Add ENV Variable[cite: 3]
- R04 Add ARG Instruction[cite: 3]
- R05 Extract Stage[cite: 3]
- R06 Inline Stage[cite: 3]
- R07 Sort Instructions — *Note: Optimize layer-cache reuse based strictly on Zhu et al. (2025) logic[cite: 3].*
- R08 Replace ADD with COPY[cite: 3]
- R09 Extract RUN Instructions[cite: 3]
- R10 Update Base Image[cite: 3]
- R11 Move Stage[cite: 3]
- R12 Remove RUN (mv command)[cite: 3]
- R13 Update RUN Instruction[cite: 3]
- R14 Rename Image[cite: 3]

## Rules for You (Claude Code)
- Build strictly within this architecture and these technology choices. Do NOT reintroduce classification engines, dimension mappings, or build-time metrics (build time is excluded from the prototype due to its high sensitivity to environmental factors)[cite: 3].
- If you believe something must deviate from this, ASK me first — do not decide alone[cite: 3].
- **Testing Requirement:** For each refactoring rule implemented in the Detection Engine, you must create a minimal pair of mock Dockerfiles (Before vs. After) inside the test suite to verify that the parsing and detection logic handles the rules perfectly[cite: 3].
- Build ONE component at a time, in pipeline order. Start with the VCS Connector[cite: 3].
- For the Detection Engine, implement the easy refactoring types first, then the hard ones[cite: 3].
- Maintain `IMPLEMENTATION_LOG.md`: after each component or non-trivial problem, record purpose, technology + version, why chosen, key design decisions, problems + solutions, how it was tested, and the single most relevant code snippet. Keep it concise and factual — it feeds the thesis Implementation chapter[cite: 3].