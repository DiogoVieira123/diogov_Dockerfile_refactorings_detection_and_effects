#!/bin/sh
# Self-contained replication of EXP-F · R08 Replace ADD with COPY · Performance
# Metric of this experiment: ΔSize (bytes, Docker daemon)
# Base image is pinned by digest and every package version is pinned, so the
# build is deterministic. See ../README.md for the guarantees and limits.
set -eu
TAG="rep-f6"

echo "Building both states with --no-cache ..."
docker build --no-cache -q -f Dockerfile.before -t "$TAG:before" . >/dev/null
docker build --no-cache -q -f Dockerfile.after  -t "$TAG:after"  . >/dev/null

size() { docker image inspect "$1" --format '{{.Size}}'; }
cves() {
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
    aquasec/trivy image --quiet --format json "$1" 2>/dev/null \
  | python3 -c "import json,sys
d=json.load(sys.stdin)
print(len({v['VulnerabilityID'] for r in (d.get('Results') or []) for v in (r.get('Vulnerabilities') or [])}))"
}

B=$(size "$TAG:before")
A=$(size "$TAG:after")
echo ""
echo "EXP-F · R08 Replace ADD with COPY · Performance"
echo "  before: $B"
echo "  after:  $A"
echo "  delta:  $((A - B))"
echo "  measured_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "  base_digest: sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc"
echo ""
echo "Compare against result.txt (values recorded in this repository)."
