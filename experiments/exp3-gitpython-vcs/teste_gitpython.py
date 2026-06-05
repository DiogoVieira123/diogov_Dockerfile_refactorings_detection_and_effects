import git

repo = git.Repo(".")

commit_a = repo.commit("2bca273")
commit_b = repo.commit("2981665")

dockerfile_antes = commit_a.tree["Dockerfile"].data_stream.read().decode("utf-8")
dockerfile_depois = commit_b.tree["Dockerfile"].data_stream.read().decode("utf-8")

print("=== ANTES ===")
print(dockerfile_antes)
print("=== DEPOIS ===")
print(dockerfile_depois)
