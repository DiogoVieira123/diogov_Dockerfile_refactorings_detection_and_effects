#!/usr/bin/env bash
#
# Maintainability validation, for inspection by the evaluation committee.
#
# Builds a throwaway Git repository holding a Dockerfile that carries two
# maintainability defects at once, and commits the corrected form over it:
#
#   before   FROM ubuntu:latest        a mutable tag, which Hadolint reports
#            RUN apt-get update        as DL3007, and two RUN instructions
#            RUN apt-get install ...   producing two layers
#
#   after    FROM ubuntu:22.04         the tag pinned, and the two commands
#            RUN apt-get update && ... chained into a single instruction
#
# The commit therefore applies two catalogue refactorings together, R02 (Update
# Base Image TAG) and R01 (Inline RUN Instructions), and exercises the two
# maintainability metrics in one run: the warning count falls as the mapped
# smell disappears, and the logical instruction count falls as the two RUNs
# become one.
#
# Usage:
#     cd <wherever the report should appear>
#     bash /path/to/run_maintenance_validation.sh
#
# Requires: git, python3, and a reachable Docker daemon (run under WSL2 or
# Linux; a daemon inside WSL2 is not reachable from a Windows interpreter).

set -euo pipefail

# --- Configuration -----------------------------------------------------------

# Located by walking up from this script's own directory until main.py is
# found, so the validation runs from a clone at any path and the script keeps
# working wherever inside the repository it is filed. Override with TOOL=...
# to point at a checkout elsewhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

locate_tool() {
    local dir="$SCRIPT_DIR"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/main.py" ]; then
            printf '%s\n' "$dir/main.py"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    return 1
}

TOOL="${TOOL:-$(locate_tool || true)}"
REPORTS_NAME="${REPORTS_NAME:-maintenance_validation_report}"

# The scratch repository is disposable and belongs in scratch space, not in the
# directory the operator is working in. /var/tmp rather than /tmp: the latter is
# cleared when the WSL2 virtual machine shuts down. Keeping it off a Windows
# mount also avoids git's dubious-ownership guard, which refuses a repository
# owned by another user.
REPO="${REPO:-/var/tmp/docker_validation}"

# The report is written beside the script, not into whatever directory the
# operator happens to be in. The script is filed with the artefacts it
# produces, so anchoring the output to its own location means the results
# land in the same place however it is invoked. Override with REPORTS=... to
# send them elsewhere.
REPORTS="${REPORTS:-$SCRIPT_DIR/$REPORTS_NAME}"

IMAGE_BEFORE="ubuntu:latest"
IMAGE_AFTER="ubuntu:22.04"

RULE="=================================================================="

step() { printf '\n%s\n  %s\n%s\n' "$RULE" "$1" "$RULE"; }
fail() { printf '\n[ERROR] %s\n' "$1" >&2; exit 1; }

# Should REPO be pointed at a Windows-mounted filesystem, the repository would
# belong to the Windows user and git would refuse to open it. Declaring this one
# path safe through the environment keeps the exception scoped to this run — no
# global configuration is written — and, unlike 'git -c', it is inherited by the
# tool's own subprocess, which reads the repository through GitPython.
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0=safe.directory
export GIT_CONFIG_VALUE_0="$REPO"

# --- Preconditions -----------------------------------------------------------

step "Step 0 - Checking preconditions"

command -v git >/dev/null 2>&1 || fail "git is not on PATH."
command -v python3 >/dev/null 2>&1 || fail "python3 is not on PATH."
command -v docker >/dev/null 2>&1 || fail "docker is not on PATH."
[ -n "$TOOL" ] && [ -f "$TOOL" ] || fail "main.py was not found above
        '$SCRIPT_DIR'. Run this script from inside the repository, or set
        TOOL to the path of main.py."

docker info >/dev/null 2>&1 || fail "No reachable Docker daemon. Both images are
        built and linted, so the daemon is required. Run this under WSL2 or
        Linux: a daemon inside WSL2 is not reachable from a Windows Python
        interpreter."

docker buildx version >/dev/null 2>&1 || fail "docker buildx is unavailable. The
        build runs on BuildKit through 'docker buildx build'."

echo "  tool         : $TOOL"
echo "  scratch repo : $REPO"
echo "  report       : $REPORTS"

# The destination is created before the tool runs, so a failure still has
# somewhere to leave its log, and raw_data exists whatever the tool does.
mkdir -p "$REPORTS/raw_data"

# --- Step 1: repository initialisation ---------------------------------------

step "Step 1 - Initialising the isolated repository"

rm -rf "$REPO"
mkdir -p "$REPO"
cd "$REPO"
git init -q
# Local to this throwaway repository; no global configuration is touched.
git config user.email "maintenance-validation@local"
git config user.name "Maintenance validation"
echo "  created $REPO"

# --- Step 2: the state carrying both defects ---------------------------------

step "Step 2 - Committing the 'before' state"

cat > Dockerfile <<DOCKERFILE
FROM $IMAGE_BEFORE
RUN apt-get update
RUN apt-get install -y curl
DOCKERFILE

git add Dockerfile
git commit -q -m "chore: initial state with a mutable tag and two RUN layers"
HASH_BEFORE="$(git rev-parse HEAD)"
echo "  $HASH_BEFORE"
sed 's/^/    /' Dockerfile

# --- Step 3: both refactorings applied ---------------------------------------

step "Step 3 - Committing the 'after' state"

cat > Dockerfile <<DOCKERFILE
FROM $IMAGE_AFTER
RUN apt-get update && apt-get install -y curl
DOCKERFILE

git add Dockerfile
git commit -q -m "refactor(dockerfile): pin the base image tag and inline the RUN instructions"
HASH_AFTER="$(git rev-parse HEAD)"
echo "  $HASH_AFTER"
sed 's/^/    /' Dockerfile

# --- Step 4: running the prototype -------------------------------------------

step "Step 4 - Running the prototype"

echo "  Building and analysing both images; this takes a few minutes."
echo

python3 "$TOOL" "$REPO" "$HASH_BEFORE" "$HASH_AFTER" -o "$REPORTS" \
    2>&1 | tee "$REPORTS/terminal_output.log"

status="${PIPESTATUS[0]}"
printf 'EXIT=%s\n' "$status" >> "$REPORTS/terminal_output.log"
[ "$status" -eq 0 ] || fail "The tool exited with code $status. See $REPORTS/terminal_output.log"

# The artefacts the committee is asked to inspect must both be present.
for required in "$REPORTS/impact_report.json" "$REPORTS/raw_data/hadolint_raw.json"; do
    [ -s "$required" ] || fail "Expected artefact missing or empty: $required"
done

# --- Step 5: pointing the committee at the evidence --------------------------

step "Step 5 - Where to inspect the result"

python3 - "$REPORTS/impact_report.json" <<'SUMMARY'
import json
import sys

report = json.loads(open(sys.argv[1], encoding="utf-8").read())
metrics = report["metrics"]

rules = ", ".join(
    f"{entry['refactoring_id']} ({entry['refactoring_name']})"
    for entry in report["refactorings_detected"]
) or "none"
print(f"  Refactorings detected : {rules}")
print()

warnings = metrics["warnings"]
instructions = metrics["logical_instructions"]
print(f"  {'metric':<24}{'before':>10}{'after':>10}{'delta':>10}")
print(
    f"  {'Warnings (47-rule)':<24}{warnings['before']:>10}"
    f"{warnings['after']:>10}{warnings['delta_warnings']:>+10}"
)
print(
    f"  {'Logical instructions':<24}{instructions['before']:>10}"
    f"{instructions['after']:>10}{instructions['delta_logical_instructions']:>+10}"
)
SUMMARY

cat <<REFERENCES

  The files to open, in full:

    $REPORTS/impact_report.json
        The structured result. 'metrics.warnings' carries the linter count
        before and after and its delta; 'metrics.logical_instructions' does
        the same for the instruction count, which falls as the two RUN
        instructions become one.

    $REPORTS/raw_data/hadolint_raw.json
        Hadolint's output exactly as emitted, never re-serialised. The DL3007
        entry raised against the mutable tag appears in the 'before' state and
        is absent from the 'after', so the warning delta can be traced to the
        specific rule that produced it.

  Also written:

    $REPORTS/human_readable_summary.txt   the report as printed above
    $REPORTS/terminal_output.log          this run, verbatim
    $REPORTS/raw_data/trivy_raw.json      the scanner output

  The scratch repository, kept only for inspection, is at
  $REPO
  It lives outside the working directory and is rebuilt from scratch on every
  run.

REFERENCES
