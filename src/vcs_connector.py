"""VCS Connector — entry point of the analysis pipeline (Chapter 5, Section 5.3).

Retrieves the complete textual content of the Dockerfile at two user-specified
commits from a local Git repository, using programmatic blob-level access to
the Git object model via GitPython (validated in Experiment 3), without a
working-tree checkout or any filesystem writes (RF1).

The blob bytes are read through GitPython's ``data_stream`` interface (a byte
stream over the Git object database) and decoded to UTF-8, so the returned
strings are byte-identical decodings of the content stored at each commit.
Repeated calls with the same commit SHA always return identical strings (RNF5),
and non-existent commits or Dockerfile paths raise specific exceptions instead
of propagating empty content downstream (RNF4).
"""

from typing import NamedTuple

import git


class VcsConnectorError(Exception):
    """Base exception for VCS Connector failures."""


class RepositoryNotFoundError(VcsConnectorError):
    """The given path is not an existing Git repository."""


class CommitNotFoundError(VcsConnectorError):
    """A given commit SHA does not resolve to a commit in the repository."""


class DockerfileNotFoundError(VcsConnectorError):
    """The Dockerfile path does not exist in the tree of the given commit."""


class DockerfilePair(NamedTuple):
    """The Dockerfile content at each of the two commits, as UTF-8 strings."""

    dockerfile_a: str
    dockerfile_b: str


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
            f"'{dockerfile_path}' does not exist at commit '{sha}' "
            f"({commit.hexsha[:7]})."
        ) from exc

    return blob.data_stream.read().decode("utf-8")


def retrieve_dockerfile_pair(
    repo_path: str,
    sha_a: str,
    sha_b: str,
    dockerfile_path: str = "Dockerfile",
) -> DockerfilePair:
    """Return the Dockerfile content at ``sha_a`` and ``sha_b`` of ``repo_path``.

    ``dockerfile_path`` is the path of the Dockerfile relative to the repository
    root, supporting repositories where the Dockerfile lives in a subdirectory.

    Raises:
        RepositoryNotFoundError: ``repo_path`` is not an existing Git repository.
        CommitNotFoundError: one of the SHAs does not resolve to a commit.
        DockerfileNotFoundError: ``dockerfile_path`` is absent from a commit's tree.
    """
    try:
        repo = git.Repo(repo_path)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError) as exc:
        raise RepositoryNotFoundError(
            f"'{repo_path}' is not an existing Git repository."
        ) from exc

    dockerfile_a = _read_dockerfile_at_commit(repo, sha_a, dockerfile_path)
    dockerfile_b = _read_dockerfile_at_commit(repo, sha_b, dockerfile_path)
    return DockerfilePair(dockerfile_a=dockerfile_a, dockerfile_b=dockerfile_b)
