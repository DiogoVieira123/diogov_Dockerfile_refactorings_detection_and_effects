#!/usr/bin/env bash
#
# measure.sh — R11 Move Stage
# Tested on Ubuntu. Measures the THREE dissertation metrics for the BEFORE and
# AFTER states of the refactoring:
#   1. Image size (bytes)        -> docker
#   2. Hadolint warnings (count) -> hadolint/hadolint container
#   3. CVEs (count)              -> aquasec/trivy container
#
# R11 extracts an entire build stage into its own standalone Dockerfile.
# BEFORE: one multi-stage Dockerfile (Dockerfile.before).
# AFTER:  the build stage is moved to Dockerfile.builder (built first, tagged
#         r11-builder) and the main Dockerfile.after uses it as a base image.
#
# The three metrics establish whether the refactoring introduces any regression.
# The maintainability benefit (separating a stage into a reusable, independent
# Dockerfile) is argued from the nature of the operation in the dissertation, not
# claimed here as a measured improvement.
#
# Usage:  bash measure.sh        (or: sudo bash measure.sh, if docker needs root)
# Output: printed to stdout AND saved to output.txt

set -u

BEFORE_TAG="r11-before:test"
AFTER_TAG="r11-after:test"
BUILDER_TAG="r11-builder:1.0"
BEFORE_DF="Dockerfile.before"
AFTER_DF="Dockerfile.after"
BUILDER_DF="Dockerfile.builder"
OUT="output.txt"

: > "$OUT"
log() { echo "$@" | tee -a "$OUT"; }

DOCKER_SOCK="/var/run/docker.sock"
if [[ -n "${DOCKER_HOST:-}" ]]; then DOCKER_SOCK="${DOCKER_HOST#unix://}"; fi

log "=================================================="
log " R11 - Move Stage"
log " Experiment 3 - Extended Catalog"
log " Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
log "=================================================="
log ""

if ! command -v docker >/dev/null 2>&1; then
  log "ERROR: docker not found in PATH. Install Docker and retry."; exit 1
fi
if ! docker info >/dev/null 2>&1; then
  log "ERROR: cannot talk to the Docker daemon."
  log "       Try: sudo bash measure.sh   (or add your user to the 'docker' group)"; exit 1
fi
log "Docker OK. Socket: ${DOCKER_SOCK}"
log ""

log "## Building images"
# BEFORE: single multi-stage build
docker build --no-cache -f "$BEFORE_DF" -t "$BEFORE_TAG" . >/dev/null 2>&1 \
  && log "  BEFORE build: OK" || log "  BEFORE build: FAILED"
# AFTER: first build the extracted builder, then the main image that uses it
docker build --no-cache -f "$BUILDER_DF" -t "$BUILDER_TAG" . >/dev/null 2>&1 \
  && log "  AFTER builder build (extracted stage): OK" || log "  AFTER builder build: FAILED"
docker build --no-cache -f "$AFTER_DF" -t "$AFTER_TAG" . >/dev/null 2>&1 \
  && log "  AFTER  main build: OK" || log "  AFTER  main build: FAILED"
log ""

log "## Metric 1 — Image size (bytes)"
log "   (final runtime image; the AFTER value is the main image, the standalone"
log "    builder image is a separate reusable artifact and not the deployed one)"
SIZE_BEFORE=$(docker image inspect "$BEFORE_TAG" --format '{{.Size}}' 2>/dev/null)
SIZE_AFTER=$(docker image inspect "$AFTER_TAG"  --format '{{.Size}}' 2>/dev/null)
log "  BEFORE: ${SIZE_BEFORE:-n/a} bytes"
log "  AFTER:  ${SIZE_AFTER:-n/a} bytes"
[[ -n "${SIZE_BEFORE:-}" && -n "${SIZE_AFTER:-}" ]] && { DELTA_SIZE=$((SIZE_AFTER - SIZE_BEFORE)); log "  Delta:  ${DELTA_SIZE} bytes"; }
log ""

log "## Metric 2 — Hadolint warnings (count + detail)"
log "   (BEFORE: the single multi-stage file; AFTER: builder + main combined)"
HADO_BEFORE=$(docker run --rm -i hadolint/hadolint hadolint -f json - < "$BEFORE_DF" 2>/dev/null | grep -o '"code"' | wc -l | tr -d ' ')
HADO_AFTER_MAIN=$(docker run --rm -i hadolint/hadolint hadolint -f json - < "$AFTER_DF" 2>/dev/null | grep -o '"code"' | wc -l | tr -d ' ')
HADO_AFTER_BUILDER=$(docker run --rm -i hadolint/hadolint hadolint -f json - < "$BUILDER_DF" 2>/dev/null | grep -o '"code"' | wc -l | tr -d ' ')
HADO_AFTER=$((HADO_AFTER_MAIN + HADO_AFTER_BUILDER))
log "  BEFORE count: ${HADO_BEFORE:-n/a} warnings"
log "  AFTER  count: ${HADO_AFTER} warnings  (main: ${HADO_AFTER_MAIN} + builder: ${HADO_AFTER_BUILDER})"
[[ -n "${HADO_BEFORE:-}" ]] && { DELTA_HADO=$((HADO_AFTER - HADO_BEFORE)); log "  Delta:        ${DELTA_HADO} warnings"; }
log ""
log "  --- Hadolint detail BEFORE (exact codes) ---"
BD=$(docker run --rm -i hadolint/hadolint hadolint - < "$BEFORE_DF" 2>/dev/null)
if [[ -z "$BD" ]]; then log "  (no warnings)"; else echo "$BD" | tee -a "$OUT"; fi
log "  --- Hadolint detail AFTER main (exact codes) ---"
AM=$(docker run --rm -i hadolint/hadolint hadolint - < "$AFTER_DF" 2>/dev/null)
if [[ -z "$AM" ]]; then log "  (no warnings)"; else echo "$AM" | tee -a "$OUT"; fi
log "  --- Hadolint detail AFTER builder (exact codes) ---"
AB=$(docker run --rm -i hadolint/hadolint hadolint - < "$BUILDER_DF" 2>/dev/null)
if [[ -z "$AB" ]]; then log "  (no warnings)"; else echo "$AB" | tee -a "$OUT"; fi
log ""

log "## Metric 3 — CVEs (Trivy)"
log "   (final runtime image in both states)"
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
log "Note: the three metrics measure regression. The maintainability benefit of"
log "Move Stage (isolating a stage into a reusable, standalone Dockerfile) is argued"
log "from the nature of the operation in the dissertation, not claimed here."
log ""
log "Done. Results saved to ${OUT}"
