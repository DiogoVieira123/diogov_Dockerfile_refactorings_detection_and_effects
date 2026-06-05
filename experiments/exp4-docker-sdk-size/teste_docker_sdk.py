import docker

# Liga ao Docker daemon local
client = docker.from_env()

# Substitui pelo nome de uma imagem que já tens localmente
# Para ver as tuas imagens corre: docker images
imagem = client.images.get("poc:baseline")

# Obtem o tamanho em bytes
tamanho_bytes = imagem.attrs["Size"]

# Converte para MB
tamanho_mb = tamanho_bytes / (1024 * 1024)

print(f"Tamanho em bytes: {tamanho_bytes}")
print(f"Tamanho em MB: {tamanho_mb:.2f} MB")
