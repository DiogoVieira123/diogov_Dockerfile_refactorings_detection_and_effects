import docker

# Liga ao Docker daemon local
client = docker.from_env()

# Imagem de teste publica e documentada: ubuntu:22.04
# (faz pull primeiro para garantir que esta presente localmente;
# o digest usado fica registado em base-image-digest.txt)
client.images.pull("ubuntu", tag="22.04")
imagem = client.images.get("ubuntu:22.04")

# Obtem o tamanho em bytes
tamanho_bytes = imagem.attrs["Size"]

# Converte para MB
tamanho_mb = tamanho_bytes / (1024 * 1024)

print(f"Tamanho em bytes: {tamanho_bytes}")
print(f"Tamanho em MB: {tamanho_mb:.2f} MB")
