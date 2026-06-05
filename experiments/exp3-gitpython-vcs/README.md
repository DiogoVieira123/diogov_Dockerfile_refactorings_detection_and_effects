# Experiment 3 — Programmatic Dockerfile Retrieval with GitPython

## Objective

Confirm that GitPython can be used to extract the content of a Dockerfile from
specific commits of a Git repository. This is the capability the VCS Connector
relies on to obtain the before and after versions of a Dockerfile from a
project's history.

## Method

A local clone of the docker/getting-started repository is opened with GitPython.
Two commits are referenced by their hash, and for each one the Dockerfile blob is
read directly from the commit tree and decoded to text. The two retrieved
versions are printed and compared.

- Repository: docker/getting-started
- Commit BEFORE (older): 2bca273
- Commit AFTER (newer): 2981665

## Result

The script returned the two Dockerfile versions as they existed at each commit.
The change between them is the addition of `--platform` arguments
(`$BUILDPLATFORM` and `$TARGETPLATFORM`) to the `FROM` instructions, enabling
multi-platform builds. Retrieving two different states of the same file at two
points in time confirms that GitPython can extract Dockerfile content per commit.
The full output of both versions is in `output.txt`.

## Validated component

VCS Connector — extraction of Dockerfile content from Git commits using
GitPython.

## How to reproduce

Requirements: Python with GitPython installed (`pip install gitpython`) and a
local clone of docker/getting-started.

    git clone https://github.com/docker/getting-started.git
    cd getting-started
    python3 teste_gitpython.py

The script reads the Dockerfile at the two commits above and prints the BEFORE
and AFTER versions, as captured in `output.txt`. The script must be run from
inside the cloned repository, since it opens the Git repository at the current
directory (`git.Repo(".")`).

## Source commits

- https://github.com/docker/getting-started
- BEFORE: 2bca273
- AFTER: 2981665
