#!/usr/bin/env bash
#
# Isolated validation of R10 (Update Base Image).
#
# Builds a throwaway Git repository holding a single-stage Dockerfile of one
# instruction, commits it twice — once on debian:12-slim, once on alpine:3.19 —
# and runs the analysis tool over the two commits. With one instruction in each
# state and nothing else in the file, every delta the tool reports is
# attributable to the base image and to nothing else.
#
# The impact report is written into a folder of the directory this script is
# invoked from, so the results land where the operator is working rather than
# beside the scratch repository.
#
# Usage:
#     cd <wherever the report should appear>
#     bash /path/to/validate_r10_isolated.sh
#
# Requires: git, python3, and a reachable Docker daemon (run under WSL2 or
# Linux; a daemon inside WSL2 is not reachable from a Windows interpreter).

set -euo pipefail

# --- Configuration -----------------------------------------------------------

# Located by walking up from this script's own directory until main.py is
# found, so the demonstration runs from a clone at any path and the script
# keeps working wherever inside the repository it is filed. Override with
# TOOL=... to point at a checkout elsewhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

locate_tool() {
    local dir="$SCRIPT_DIR"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/main.py" ]; then
            printf '%s
' "$dir/main.py"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    return 1
}

TOOL="${TOOL:-$(locate_tool || true)}"
REPO="${REPO:-/var/tmp/test-r10-isolated}"
OUTPUT_NAME="${OUTPUT_NAME:-r10_isolated_report}"

IMAGE_BEFORE="debian:12-slim"
IMAGE_AFTER="alpine:3.19"

# The report is written beside the script, not into whatever directory the
# operator happens to be in. The script is filed with the artefacts it
# produces, so anchoring the output to its own location means the results
# land in the same place however it is invoked. Override with OUTPUT=... to
# send them elsewhere.
OUTPUT="${OUTPUT:-$SCRIPT_DIR/$OUTPUT_NAME}"

RULE="------------------------------------------------------------------"

step() { printf '\n%s\n  %s\n%s\n' "$RULE" "$1" "$RULE"; }
fail() { printf '\n[ERROR] %s\n' "$1" >&2; exit 1; }

# --- Preconditions -----------------------------------------------------------

step "Checking preconditions"

command -v git >/dev/null 2>&1 || fail "git is not on PATH."
command -v python3 >/dev/null 2>&1 || fail "python3 is not on PATH."
[ -n "$TOOL" ] && [ -f "$TOOL" ] || fail "main.py was not found above
        '$SCRIPT_DIR'. Run this script from inside the repository, or set
        TOOL to the path of main.py."

if ! docker info >/dev/null 2>&1; then
    fail "No reachable Docker daemon. Stages 3 and 4 build both images and run
        Hadolint and Trivy against them, so the daemon is required. Run this
        under WSL2 or Linux: a daemon inside WSL2 is not reachable from a
        Windows Python interpreter."
fi

echo "  tool        : $TOOL"
echo "  scratch repo: $REPO"
echo "  report goes to: $OUTPUT"

# --- Repository preparation --------------------------------------------------

step "Preparing the scratch repository"

rm -rf "$REPO"
mkdir -p "$REPO"
cd "$REPO"
git init -q
# A repository with no identity configured cannot commit; these are local to
# this throwaway clone and touch no global configuration.
git config user.email "r10-validation@local"
git config user.name "R10 validation"
echo "  initialised $REPO"

# --- Commit before: the heavier base -----------------------------------------

step "Commit before: $IMAGE_BEFORE"

echo "FROM $IMAGE_BEFORE" > Dockerfile
git add Dockerfile
git commit -q -m "debian base"
HASH_BEFORE="$(git rev-parse HEAD)"
echo "  $HASH_BEFORE"

# --- Commit after: the lighter base ------------------------------------------

step "Commit after: $IMAGE_AFTER"

echo "FROM $IMAGE_AFTER" > Dockerfile
git add Dockerfile
git commit -q -m "alpine base"
HASH_AFTER="$(git rev-parse HEAD)"
echo "  $HASH_AFTER"

# --- Running the tool --------------------------------------------------------

step "Running the analysis tool"

mkdir -p "$OUTPUT"
echo "  building both images and scanning them; this takes a few minutes"
echo

python3 "$TOOL" "$REPO" "$HASH_BEFORE" "$HASH_AFTER" -o "$OUTPUT" \
    2>&1 | tee "$OUTPUT/terminal_output.log"

status="${PIPESTATUS[0]}"
printf 'EXIT=%s\n' "$status" >> "$OUTPUT/terminal_output.log"
[ "$status" -eq 0 ] || fail "The tool exited with code $status. See $OUTPUT/terminal_output.log"

# --- Result ------------------------------------------------------------------

step "Impact report"

cat "$OUTPUT/human_readable_summary.txt"

step "Written to $OUTPUT"

ls -1 "$OUTPUT"
ls -1 "$OUTPUT/raw_data" | sed 's|^|raw_data/|'
