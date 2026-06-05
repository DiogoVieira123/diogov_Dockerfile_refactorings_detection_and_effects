#!/usr/bin/env bash
set -e

R=$1
if [ -z "$R" ]; then echo "Usage: ./run_one.sh poc-1-inline-run"; exit 1; fi

cd "$R"
TAG_BEFORE="${R}:before"
TAG_AFTER="${R}:after"

echo "==> Build BEFORE"
docker build -t "$TAG_BEFORE" -f before/Dockerfile before/

echo "==> Build AFTER"
docker build -t "$TAG_AFTER" -f after/Dockerfile after/

echo "==> Hadolint"
docker run --rm -i hadolint/hadolint hadolint --format json - < before/Dockerfile > hadolint-before.json || true
docker run --rm -i hadolint/hadolint hadolint --format json - < after/Dockerfile  > hadolint-after.json  || true

echo "==> Trivy"
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy image --format json --quiet "$TAG_BEFORE" > trivy-before.json
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy image --format json --quiet "$TAG_AFTER"  > trivy-after.json

echo "==> Size (Docker SDK)"
python3 - <<PYEOF
import docker
c = docker.from_env()
before_bytes = c.images.get("$TAG_BEFORE").attrs["Size"]
after_bytes  = c.images.get("$TAG_AFTER").attrs["Size"]
open("size-before.txt","w").write(str(before_bytes) + "\n")
open("size-after.txt","w").write(str(after_bytes) + "\n")
print(f"before_bytes={before_bytes}")
print(f"after_bytes ={after_bytes}")
print(f"delta_size  ={after_bytes - before_bytes:+d}")
PYEOF

echo "==> Done $R"
