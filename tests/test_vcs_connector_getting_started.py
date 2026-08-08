"""Integration test replicating Experiment 3 against docker/getting-started.

Requires a local clone of https://github.com/docker/getting-started. Point the
GETTING_STARTED_REPO environment variable at the clone; the test is skipped
when it is not set or the path does not exist.

    git clone https://github.com/docker/getting-started.git
    GETTING_STARTED_REPO=./getting-started python -m pytest tests/test_vcs_connector_getting_started.py
"""

import os

import pytest

from src.vcs_connector import retrieve_dockerfile_pair

COMMIT_BEFORE = "2bca273"
COMMIT_AFTER = "2981665"

repo_path = os.environ.get("GETTING_STARTED_REPO", "")
pytestmark = pytest.mark.skipif(
    not (repo_path and os.path.isdir(repo_path)),
    reason="GETTING_STARTED_REPO not set to a local docker/getting-started clone",
)


def test_experiment_3_retrieval():
    pair = retrieve_dockerfile_pair(repo_path, COMMIT_BEFORE, COMMIT_AFTER)

    # The change between the two commits is the addition of --platform
    # arguments to the FROM instructions (see experiments/exp3-gitpython-vcs).
    assert "--platform" not in pair.dockerfile_a
    assert "--platform=$BUILDPLATFORM" in pair.dockerfile_b
    assert "--platform=$TARGETPLATFORM" in pair.dockerfile_b
    assert pair.dockerfile_a.startswith("# Install the base requirements for the app.")
    assert pair.dockerfile_a != pair.dockerfile_b
