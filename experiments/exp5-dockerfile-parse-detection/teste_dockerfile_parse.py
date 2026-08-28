from dockerfile_parse import DockerfileParser

# Parse the before Dockerfile
dfp = DockerfileParser()
with open('Dockerfile-antes') as f:
    dfp.content = f.read()
run_antes = [s for s in dfp.structure if s['instruction'] == 'RUN']

# Parse the after Dockerfile
with open('Dockerfile-depois') as f:
    dfp.content = f.read()
run_depois = [s for s in dfp.structure if s['instruction'] == 'RUN']

# Show the results
print(f"RUN instructions before: {len(run_antes)}")
print(f"RUN instructions after: {len(run_depois)}")

# Detection rule
if len(run_antes) > len(run_depois):
    print(f"Refactoring detected: RUN consolidation ({len(run_antes)} → {len(run_depois)})")
else:
    print("No RUN consolidation detected.")
