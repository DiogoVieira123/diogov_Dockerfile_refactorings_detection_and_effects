import sys

import git

# Repository path: first command-line argument, defaulting to the current
# directory (the original behaviour). Example:
#   python3 teste_gitpython.py /path/to/getting-started
REPO_PATH = sys.argv[1] if len(sys.argv) > 1 else "."

repo = git.Repo(REPO_PATH)

commit_a = repo.commit("2bca273")
commit_b = repo.commit("2981665")

dockerfile_antes = commit_a.tree["Dockerfile"].data_stream.read().decode("utf-8")
dockerfile_depois = commit_b.tree["Dockerfile"].data_stream.read().decode("utf-8")

print("=== ANTES ===")
print(dockerfile_antes)
print("=== DEPOIS ===")
print(dockerfile_depois)
