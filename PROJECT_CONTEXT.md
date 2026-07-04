# Project Context — Master's Dissertation Prototype
# "Dockerfile Refactorings: Detection and Effects" (ISEP)

## Goal
A Python 3 tool that receives a Git repository path and two commit identifiers, extracts the Dockerfile at each commit from version history, detects whether a structural refactoring occurred between them, classifies that refactoring by its primary quality dimension, and produces an impact report quantifying the change across three quality axes: Performance, Security, and Maintainability.

## Input / Output
- INPUT: a Git repository path + two commit SHAs (with optional subdirectory support).
- OUTPUT: an impact report (JSON format, RFC 8259) + a human-readable text summary detailing the detected refactoring type, its dimension classification, metrics, and trade-off flags.

## Pipeline (FIXED — from thesis Chapter 5, do not change)
VCS Connector → Detection Engine → Classification Engine → [Performance Analyzer + Data Extractor (Parallel Execution)] → Report Generator

## The THREE Metrics Measured (FIXED — do not add build time)
- **Image Size** → Performance (Docker SDK, exact uncompressed VirtualSize byte count via 64-bit integer).
- **Hadolint Warnings** → Maintainability (Hadolint JSON output, filtered strictly by maintainability rules like DL3059 and DL3020).
- **CVE Count** → Security (Trivy JSON output, structured vulnerability count vector by severity tier).

## Components, Technologies and Responsibilities (FIXED)
- **VCS Connector** — GitPython. Navigates the Git object model natively. Retrieves the Dockerfile content at any commit as a UTF-8 string WITHOUT a working-tree checkout or filesystem writes. Raises explicit exceptions for missing files or commits.
- **Detection Engine** — dockerfile-parse. Reconstructs multi-line RUN instructions (backslash continuation) into their logical single-unit form BEFORE detection to prevent false instruction counts. Detects all 14 refactoring types (R01–R14). Uses a content preservation check to resolve consolidation-versus-deletion ambiguities.
- **Classification Engine** — Maps each detected refactoring to its primary and secondary quality dimension using a deterministic lookup table based strictly on the extended catalogue (Table 5.3).
- **Performance Analyzer** — Docker SDK for Python. Builds images locally and extracts exact raw byte integers using `image.attrs["Size"]`, avoiding Docker CLI text-rounding errors. Computes a signed delta (ΔSize).
- **Data Extractor** — Runs Hadolint and Trivy concurrently in Docker containers (`hadolint/hadolint` and `aquasec/trivy`) to minimize execution time. Normalizes their heterogeneous JSON schemas and filters Hadolint outputs to retain only maintainability-related warnings.
- **Report Generator** — Consumes outputs, computes signed deltas (ΔSize, ΔCVEs, ΔWarnings), and applies trade-off detection (raising a trade-off flag whenever a secondary dimension degradation opposes a primary dimension improvement).

## The 14 Refactoring Types to Detect (Table 5.3 Mappings)
- R01 Inline RUN Instructions (Primary: Performance, Secondary: Maintainability)
- R02 Update Base Image TAG (Primary: Maintainability, Secondary: Security)
- R03 Add ENV Variable (Primary: Maintainability, Secondary: None)
- R04 Add ARG Instruction (Primary: Maintainability, Secondary: None)
- R05 Extract Stage (Primary: Performance, Secondary: Maintainability)
- R06 Inline Stage (Primary: Maintainability, Secondary: None)
- R07 Sort Instructions (Primary: Performance, Secondary: Maintainability) — *Note: Optimize layer-cache reuse based strictly on Zhu et al. (2025) logic.*
- R08 Replace ADD with COPY (Primary: Maintainability, Secondary: Security)
- R09 Extract RUN Instructions (Primary: Maintainability, Secondary: None)
- R10 Update Base Image (Primary: Security, Secondary: Performance)
- R11 Move Stage (Primary: Maintainability, Secondary: None)
- R12 Remove RUN (mv command) (Primary: Performance, Secondary: None)
- R13 Update RUN Instruction (Primary: Maintainability, Secondary: None)
- R14 Rename Image (Primary: Maintainability, Secondary: None)

## Rules for You (Claude Code)
- Build strictly within this architecture and these technology choices. Do NOT introduce a different design, swap libraries, or add an environmental build-time metric.
- If you believe something must deviate from this, ASK me first — do not decide alone.
- **Testing Requirement:** For each refactoring rule implemented in the Detection Engine, you must create a minimal pair of mock Dockerfiles (Before vs. After) inside the test suite to verify that the parsing and detection logic handles the rules perfectly.
- Build ONE component at a time, in pipeline order. Start with the VCS Connector.
- For the Detection Engine, implement the easy refactoring types first, then the hard ones.
- Maintain `IMPLEMENTATION_LOG.md`: after each component or non-trivial problem, record purpose, technology + version, why chosen, key design decisions, problems + solutions, how it was tested, and the single most relevant code snippet. Keep it concise and factual — it feeds the thesis Implementation chapter.