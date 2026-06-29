#!/usr/bin/env bash
#
# measure.sh — R12 - Remove RUN Instruction (mv command)
# Tested on Ubuntu. Measures the THREE dissertation metrics for BEFORE and AFTER,
# and records the EXACT Hadolint warnings (codes + descriptions), not just counts:
#   1. Image size (bytes)        -> docker
#   2. Hadolint warnings         -> hadolint/hadolint container (count + detail)
#   3. CVEs (count)              -> aquasec/trivy container
#
# The three metrics establish whether the refactoring introduces any regression.
# The main measured effect is on image size (removing the RUN mv layers).
#
# Usage:  bash measure.sh        (or: sudo bash measure.sh, if docker needs root)
# Output: printed to stdout AND saved to output.txt

set -u
BEFORE_TAG="r12-before:test"
AFTER_TAG="r12-after:test"
BEFORE_DF="Dockerfile.before"
AFTER_DF="Dockerfile.after"
OUT="output.txt"

: > "$OUT"
log() { echo "$@" | tee -a "$OUT"; }
DOCKER_SOCK="/var/run/docker.sock"
if [[ -n "${DOCKER_HOST:-}" ]]; then DOCKER_SOCK="${DOCKER_HOST#unix://}"; fi

log "=================================================="
log " R12 - Remove RUN Instruction (mv command)"
log " Experiment 4 - Extended Catalog"
log " Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
log "=================================================="
log ""

if ! command -v docker >/dev/null 2>&1; then
  log "ERROR: docker not found in PATH."; exit 1
fi
if ! docker info >/dev/null 2>&1; then
  log "ERROR: cannot talk to the Docker daemon."
  log "       Try: sudo bash measure.sh   (or add your user to the 'docker' group)"; exit 1
fi
log "Docker OK. Socket: ${DOCKER_SOCK}"
log ""

log "## Building images"
docker build --no-cache -f "$BEFORE_DF" -t "$BEFORE_TAG" . >/dev/null 2>&1 \
  && log "  BEFORE build: OK" || log "  BEFORE build: FAILED"
docker build --no-cache -f "$AFTER_DF" -t "$AFTER_TAG" . >/dev/null 2>&1 \
  && log "  AFTER  build: OK" || log "  AFTER  build: FAILED"
log ""

log "## Metric 1 — Image size (bytes)"
SIZE_BEFORE=$(docker image inspect "$BEFORE_TAG" --format '{{.Size}}' 2>/dev/null)
SIZE_AFTER=$(docker image inspect "$AFTER_TAG"  --format '{{.Size}}' 2>/dev/null)
log "  BEFORE: ${SIZE_BEFORE:-n/a} bytes"
log "  AFTER:  ${SIZE_AFTER:-n/a} bytes"
[[ -n "${SIZE_BEFORE:-}" && -n "${SIZE_AFTER:-}" ]] && { DELTA_SIZE=$((SIZE_AFTER - SIZE_BEFORE)); log "  Delta:  ${DELTA_SIZE} bytes"; }
log ""

log "## Metric 2 — Hadolint warnings (count + detail)"
HADO_BEFORE=$(docker run --rm -i hadolint/hadolint hadolint -f json - < "$BEFORE_DF" 2>/dev/null | grep -o '"code"' | wc -l | tr -d ' ')
HADO_AFTER=$(docker run --rm -i hadolint/hadolint hadolint -f json - < "$AFTER_DF" 2>/dev/null | grep -o '"code"' | wc -l | tr -d ' ')
log "  BEFORE count: ${HADO_BEFORE:-n/a} warnings"
log "  AFTER  count: ${HADO_AFTER:-n/a} warnings"
[[ -n "${HADO_BEFORE:-}" && -n "${HADO_AFTER:-}" ]] && { DELTA_HADO=$((HADO_AFTER - HADO_BEFORE)); log "  Delta:        ${DELTA_HADO} warnings"; }
log ""
log "  --- Hadolint detail BEFORE (exact codes) ---"
BEFORE_DETAIL=$(docker run --rm -i hadolint/hadolint hadolint - < "$BEFORE_DF" 2>/dev/null)
if [[ -z "$BEFORE_DETAIL" ]]; then log "  (no warnings)"; else echo "$BEFORE_DETAIL" | tee -a "$OUT"; fi
log "  --- Hadolint detail AFTER (exact codes) ---"
AFTER_DETAIL=$(docker run --rm -i hadolint/hadolint hadolint - < "$AFTER_DF" 2>/dev/null)
if [[ -z "$AFTER_DETAIL" ]]; then log "  (no warnings)"; else echo "$AFTER_DETAIL" | tee -a "$OUT"; fi
log ""

log "## Metric 3 — CVEs (Trivy)"
CVE_BEFORE=$(docker run --rm -v "${DOCKER_SOCK}:/var/run/docker.sock" aquasec/trivy image --quiet --format json "$BEFORE_TAG" 2>/dev/null | grep -o '"VulnerabilityID"' | wc -l | tr -d ' ')
CVE_AFTER=$(docker run --rm -v "${DOCKER_SOCK}:/var/run/docker.sock" aquasec/trivy image --quiet --format json "$AFTER_TAG" 2>/dev/null | grep -o '"VulnerabilityID"' | wc -l | tr -d ' ')
log "  BEFORE: ${CVE_BEFORE:-n/a} CVEs"
log "  AFTER:  ${CVE_AFTER:-n/a} CVEs"
[[ -n "${CVE_BEFORE:-}" && -n "${CVE_AFTER:-}" ]] && { DELTA_CVE=$((CVE_AFTER - CVE_BEFORE)); log "  Delta:  ${DELTA_CVE} CVEs"; }
log ""

log "=================================================="
log " SUMMARY (Delta = AFTER - BEFORE)"
log "=================================================="
log "  Image size : ${DELTA_SIZE:-n/a} bytes"
log "  Hadolint   : ${DELTA_HADO:-n/a} warnings"
log "  CVEs       : ${DELTA_CVE:-n/a}"
log ""
log "Done. Results saved to ${OUT}"
