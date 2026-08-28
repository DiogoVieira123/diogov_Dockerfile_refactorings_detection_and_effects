#!/bin/sh
# Self-contained replication of EXP-A · R01 Inline RUN Instructions · Security
# Metric of this experiment: ΔCVEs (distinct VulnerabilityID, Trivy)
# Base image is pinned by digest and every package version is pinned, so the
# build is deterministic. See ../README.md for the guarantees and limits.
set -eu
TAG="rep-a1"

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

B=$(cves "$TAG:before")
A=$(cves "$TAG:after")
echo ""
echo "EXP-A · R01 Inline RUN Instructions · Security"
echo "  before: $B"
echo "  after:  $A"
echo "  delta:  $((A - B))"
echo "  measured_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "  base_digest: sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818"
echo ""
echo "Compare against result.txt (values recorded in this repository)."
