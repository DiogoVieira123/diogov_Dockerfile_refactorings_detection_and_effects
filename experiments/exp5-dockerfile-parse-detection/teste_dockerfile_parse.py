from dockerfile_parse import DockerfileParser

# Parseia o Dockerfile antes
dfp = DockerfileParser()
with open('Dockerfile-antes') as f:
    dfp.content = f.read()
run_antes = [s for s in dfp.structure if s['instruction'] == 'RUN']

# Parseia o Dockerfile depois
with open('Dockerfile-depois') as f:
    dfp.content = f.read()
run_depois = [s for s in dfp.structure if s['instruction'] == 'RUN']

# Mostra os resultados
print(f"Instruções RUN antes: {len(run_antes)}")
print(f"Instruções RUN depois: {len(run_depois)}")

# Regra de detecção
if len(run_antes) > len(run_depois):
    print(f"Refatoração detectada: Consolidação de RUN ({len(run_antes)} → {len(run_depois)})")
else:
    print("Nenhuma consolidação de RUN detectada.")
