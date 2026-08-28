import docker

# Connect to the local Docker daemon
client = docker.from_env()

# Public, documented test image: ubuntu:22.04
# (pull it first to make sure it is present locally;
# the digest used is recorded in base-image-digest.txt)
client.images.pull("ubuntu", tag="22.04")
imagem = client.images.get("ubuntu:22.04")

# Get the size in bytes
tamanho_bytes = imagem.attrs["Size"]

# Convert to MB
tamanho_mb = tamanho_bytes / (1024 * 1024)

print(f"Size in bytes: {tamanho_bytes}")
print(f"Size in MB: {tamanho_mb:.2f} MB")
