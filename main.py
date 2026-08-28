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
    return parser


def main(argv=None) -> int:
    arguments = build_parser().parse_args(argv)

    stages = (
        (VcsConnectorError, EXIT_VCS),
        (DockerfileParseError, EXIT_PARSE),
        (CommitContextError, EXIT_BUILD),
        (ImageBuildError, EXIT_BUILD),
        (PerformanceAnalyzerError, EXIT_SIZE),
        (DataExtractorError, EXIT_EXTRACT),
        (OSError, EXIT_REPORT),
    )

    try:
        artifacts = run_analysis(
            arguments.repository,
            arguments.commit_before,
            arguments.commit_after,
            arguments.output,
            dockerfile_path=arguments.dockerfile,
        )
    except tuple(exception for exception, _ in stages) as failure:
        code = next(c for exception, c in stages if isinstance(failure, exception))
        print(f"Analysis failed: {failure}", file=sys.stderr)
        return code

    print(Path(artifacts.summary_text).read_text(encoding="utf-8"))
    print(f"Report written to {Path(arguments.output).resolve()}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
