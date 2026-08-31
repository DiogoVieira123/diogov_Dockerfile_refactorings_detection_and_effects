"""Command-line entry point for the Dockerfile refactoring impact analyser.

Receives a local Git repository and two commits, runs the full pipeline, and
writes the impact report:

    python main.py <repository> <commit_before> <commit_after> [-o <directory>]

Example, replicating the R09 catalogue experiment:

    python main.py ./my-repo 2bca273 2981665 -o ./report

The exit code identifies which stage failed, so the distinct exceptions RNF4
requires stay distinguishable at the process boundary rather than collapsing
into a single failure:

    0  analysis completed
    1  repository, commit or Dockerfile not found        (Stage 1)
    2  a Dockerfile state could not be parsed            (Stage 2)
    3  a commit's file tree could not be exported, the daemon is unreachable,
       or a build failed                                 (Stage 3, preparation)
    4  an image size could not be measured               (Stage 3, size)
    5  Hadolint or Trivy failed                          (Stage 3, extraction)
    6  the report could not be written                   (Stage 4)

Each state is built against its own commit's file tree, exported to a
temporary directory and removed when the analysis ends, so the measurement
reflects the repository as it stood at each commit rather than as the working
tree stands today.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.data_extractor import DataExtractorError
from src.detection_engine import DockerfileParseError
from src.image_builder import ImageBuildError
from src.performance_analyzer import PerformanceAnalyzerError
from src.pipeline import DEFAULT_DOCKERFILE_PATH, CommitContextError, run_analysis
from src.vcs_connector import VcsConnectorError

EXIT_OK = 0
EXIT_VCS = 1
EXIT_PARSE = 2
EXIT_BUILD = 3
EXIT_SIZE = 4
EXIT_EXTRACT = 5
EXIT_REPORT = 6


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=(
            "Detect the structural refactoring between two commits of a "
            "Dockerfile and measure its impact on image size, vulnerabilities, "
            "maintainability warnings and logical instruction count."
        ),
    )
    parser.add_argument("repository", help="path of a local Git repository")
    parser.add_argument("commit_before", help="SHA of the earlier commit")
    parser.add_argument("commit_after", help="SHA of the later commit")
    parser.add_argument(
        "-o",
        "--output",
        default="./impact_report",
        help="directory for the report artifacts (default: ./impact_report)",
    )
    parser.add_argument(
        "-d",
        "--dockerfile",
        default=DEFAULT_DOCKERFILE_PATH,
        help=(
            "Dockerfile path relative to the repository root "
            f"(default: {DEFAULT_DOCKERFILE_PATH})"
        ),
    )
    parser.add_argument(
        "-c",
        "--context",
        default=None,
        metavar="PATH",
        help=(
            "build context directory, relative to the repository root. "
            "Defaults to the directory holding the Dockerfile, which is what "
            "`docker build <dir>` uses; give a path here when the COPY and ADD "
            "sources live somewhere else, such as the repository root of a "
            "monorepo"
        ),
    )
    return parser


def main(argv=None) -> int:
    arguments = build_parser().parse_args(argv)

    # Each entry names the exception, the exit code, and the stage to report.
    # The stage label is what makes a failure legible in a captured log: the
    # reader sees which stage broke without having to map an exception type
    # back onto the pipeline.
    stages = (
        (VcsConnectorError, EXIT_VCS, "Stage 1 (data collection)"),
        (DockerfileParseError, EXIT_PARSE, "Stage 2 (refactoring detection)"),
        (CommitContextError, EXIT_BUILD, "Stage 3 (preparation: commit export)"),
        (ImageBuildError, EXIT_BUILD, "Stage 3 (preparation: image build)"),
        (PerformanceAnalyzerError, EXIT_SIZE, "Stage 3 (measurement: image size)"),
        (DataExtractorError, EXIT_EXTRACT, "Stage 3 (measurement: extraction)"),
        (OSError, EXIT_REPORT, "Stage 4 (report generation)"),
    )

    try:
        artifacts = run_analysis(
            arguments.repository,
            arguments.commit_before,
            arguments.commit_after,
            arguments.output,
            dockerfile_path=arguments.dockerfile,
            build_context=arguments.context,
        )
    except tuple(exception for exception, _, _ in stages) as failure:
        code, stage = next(
            (c, s) for exception, c, s in stages if isinstance(failure, exception)
        )
        # Reported before returning, so the analysis stops here — no partial
        # report is written — while the log still records exactly what broke,
        # on which pair, and why.
        print(
            f"[ERROR] {stage} failed for {arguments.dockerfile} "
            f"@ {arguments.commit_before}..{arguments.commit_after}",
            file=sys.stderr,
        )
        print(f"[ERROR] reason: {failure}", file=sys.stderr)
        print(f"[ERROR] exit code {code}; analysis stopped, no report written.",
              file=sys.stderr)
        return code

    print(Path(artifacts.summary_text).read_text(encoding="utf-8"))
    print(f"Report written to {Path(arguments.output).resolve()}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
