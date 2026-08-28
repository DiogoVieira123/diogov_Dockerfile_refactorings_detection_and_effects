"""Unit tests for the VCS Connector (RF1, RNF4, RNF5).

A temporary Git repository is built inside the test fixture, so the suite runs
offline and deterministically. The integration check against the public
docker/getting-started repository (Experiment 3) is in
``test_vcs_connector_getting_started.py``.
"""

import git
import pytest

from src.vcs_connector import (
    CommitNotFoundError,
    DockerfileNotFoundError,
    RepositoryNotFoundError,
    retrieve_dockerfile_pair,
)

DOCKERFILE_V1 = "FROM ubuntu:22.04\nRUN apt-get update\n"
DOCKERFILE_V2 = "FROM alpine:3.19\nRUN apk add --no-cache curl\n"
DOCKERFILE_SUBDIR = "FROM python:3.12-slim\n"


@pytest.fixture()
def sample_repo(tmp_path):
    """A repo with three commits: no Dockerfile, Dockerfile v1, Dockerfile v2.

    The second version also adds a Dockerfile inside a subdirectory to test
    non-root Dockerfile paths. Returns (repo_path, sha_empty, sha_v1, sha_v2).
    """
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "test@example.com")

    # write_bytes avoids Windows newline translation, so the committed blobs
    # hold exactly these bytes and the byte-identical assertions are exact.
    (tmp_path / "README.md").write_bytes(b"initial\n")
    repo.index.add(["README.md"])
    sha_empty = repo.index.commit("no dockerfile yet").hexsha

    (tmp_path / "Dockerfile").write_bytes(DOCKERFILE_V1.encode("utf-8"))
    repo.index.add(["Dockerfile"])
    sha_v1 = repo.index.commit("add dockerfile v1").hexsha

    (tmp_path / "Dockerfile").write_bytes(DOCKERFILE_V2.encode("utf-8"))
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "Dockerfile").write_bytes(DOCKERFILE_SUBDIR.encode("utf-8"))
    repo.index.add(["Dockerfile", "app/Dockerfile"])
    sha_v2 = repo.index.commit("dockerfile v2 + subdir dockerfile").hexsha

    repo.close()
    return str(tmp_path), sha_empty, sha_v1, sha_v2


def test_retrieves_both_versions_byte_identical(sample_repo):
    repo_path, _, sha_v1, sha_v2 = sample_repo
    pair = retrieve_dockerfile_pair(repo_path, sha_v1, sha_v2)
    assert pair.dockerfile_a == DOCKERFILE_V1
    assert pair.dockerfile_b == DOCKERFILE_V2


def test_accepts_abbreviated_shas(sample_repo):
    repo_path, _, sha_v1, sha_v2 = sample_repo
    pair = retrieve_dockerfile_pair(repo_path, sha_v1[:7], sha_v2[:7])
    assert pair == (DOCKERFILE_V1, DOCKERFILE_V2)


def test_supports_dockerfile_in_subdirectory(sample_repo):
    repo_path, _, _, sha_v2 = sample_repo
    pair = retrieve_dockerfile_pair(
        repo_path, sha_v2, sha_v2, dockerfile_path="app/Dockerfile"
    )
    assert pair.dockerfile_a == DOCKERFILE_SUBDIR


def test_does_not_touch_working_tree(sample_repo, tmp_path):
    repo_path, _, sha_v1, sha_v2 = sample_repo
    retrieve_dockerfile_pair(repo_path, sha_v1, sha_v2)
    # Working tree still holds v2; retrieving v1 came from the object database.
    assert (tmp_path / "Dockerfile").read_text(encoding="utf-8") == DOCKERFILE_V2
    assert not git.Repo(repo_path).is_dirty(untracked_files=True)


def test_same_sha_always_yields_same_output(sample_repo):
    repo_path, _, sha_v1, sha_v2 = sample_repo
    first = retrieve_dockerfile_pair(repo_path, sha_v1, sha_v2)
    second = retrieve_dockerfile_pair(repo_path, sha_v1, sha_v2)
    assert first == second


def test_missing_commit_raises(sample_repo):
    repo_path, _, sha_v1, _ = sample_repo
    with pytest.raises(CommitNotFoundError):
        retrieve_dockerfile_pair(repo_path, "0000000", sha_v1)


def test_missing_dockerfile_raises(sample_repo):
    repo_path, sha_empty, sha_v1, _ = sample_repo
    with pytest.raises(DockerfileNotFoundError):
        retrieve_dockerfile_pair(repo_path, sha_empty, sha_v1)


def test_missing_repository_raises(tmp_path):
    with pytest.raises(RepositoryNotFoundError):
        retrieve_dockerfile_pair(str(tmp_path / "nope"), "abc1234", "def5678")
