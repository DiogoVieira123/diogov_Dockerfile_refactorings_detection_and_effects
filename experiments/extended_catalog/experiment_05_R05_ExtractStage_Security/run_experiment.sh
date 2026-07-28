#!/bin/sh
# Replication entry point — identical in every experiment of this catalogue:
#     sh run_experiment.sh
# Metric of this experiment: ΔCVEs (distinct VulnerabilityID, Trivy, final image)
# Trivy runs as a container, so no local installation is required.
# See ../README.md for prerequisites and pinning mechanisms.
set -eu
TAG="rep-r05"

echo "Building both states with --no-cache ..."
docker build --no-cache -q -f R05_cargo_before.Dockerfile -t "$TAG:before" . >/dev/null
docker build --no-cache -q -f R05_cargo_after.Dockerfile  -t "$TAG:after"  . >/dev/null

if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi

cves() {
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
    aquasec/trivy image --quiet --format json "$1" 2>/dev/null \
  | "$PY" -c "import json,sys
d=json.load(sys.stdin)
print(len({v['VulnerabilityID'] for r in (d.get('Results') or []) for v in (r.get('Vulnerabilities') or [])}))"
}

B=$(cves "$TAG:before")
A=$(cves "$TAG:after")

# raw scanner output, kept as this experiment's artefacts
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy image --quiet "$TAG:before" > log_before.txt 2>/dev/null || true
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy image --quiet "$TAG:after"  > log_after.txt  2>/dev/null || true

echo ""
echo "EXP-05 · R05 Extract Stage · Security"
echo "  before: $B"
echo "  after:  $A"
echo "  delta:  $((A - B))"
echo "  measured_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""
echo "Compare against result.txt (values recorded in this repository)."
