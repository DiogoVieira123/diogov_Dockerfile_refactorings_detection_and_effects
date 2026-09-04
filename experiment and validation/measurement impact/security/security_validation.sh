#!/usr/bin/env bash
#
# End-to-end security validation, for inspection by the evaluation committee.
#
# Builds a throwaway Git repository holding a minimal Node application, commits
# it twice — once on the Debian base, once on the Alpine base, with the
# Node version held constant — and runs the analysis tool over the two
# commits. The Dockerfile is identical in both states apart from the tag, so
# every delta the tool reports is attributable to the change of base operating
# system and to nothing else.
#
# Two artefacts are produced for inspection:
#   impact_report.json         the structured result: rules detected, the CVE
#                              delta, and its breakdown by severity
#   raw_data/trivy_raw.json    the scanner output as Trivy emitted it, kept
#                              verbatim so every count can be traced to source
#
# Usage:
#     cd <wherever the demonstration should be created>
#     bash /path/to/security_validation.sh
#
# Requires: git, python3, and a reachable Docker daemon (run under WSL2 or
# Linux; a daemon inside WSL2 is not reachable from a Windows interpreter).
# Both base images are pulled if absent, which is roughly 1 GB on a cold cache.

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
            printf '%s\n' "$dir/main.py"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    return 1
}

TOOL="${TOOL:-$(locate_tool || true)}"
ENV_DIR="${ENV_DIR:-demo_test_env}"
SCRATCH_ROOT="${SCRATCH_ROOT:-/var/tmp}"
REPORTS_NAME="${REPORTS_NAME:-security_validation_report}"

IMAGE_BEFORE="node:18.16.0"
IMAGE_AFTER="node:18.16.0-alpine"

# The scratch repository is disposable and belongs in scratch space, not in
# the directory the operator is working in. /var/tmp rather than /tmp: the
# latter is cleared when the WSL2 virtual machine shuts down. Keeping it off
# a Windows mount also avoids git's dubious-ownership guard, which refuses a
# repository owned by another user.
REPO="${REPO:-$SCRATCH_ROOT/$ENV_DIR}"

# The report is written beside the script, not into whatever directory the
# operator happens to be in. The script is filed with the artefacts it
# produces, so anchoring the output to its own location means the results
# land in the same place however it is invoked. Override with REPORTS=... to
# send them elsewhere.
REPORTS="${REPORTS:-$SCRIPT_DIR/$REPORTS_NAME}"

# Should REPO be pointed at a Windows-mounted filesystem (/mnt/c under WSL2),
# the repository would belong to the Windows user and git would refuse to open
# it: 'detected dubious ownership'. Declaring this one path safe
# through the environment keeps the exception scoped to this demonstration —
# no global configuration is written — and, unlike 'git -c', it is inherited
# by the tool's own subprocess, which reads the repository through GitPython.
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0=safe.directory
export GIT_CONFIG_VALUE_0="$REPO"

RULE="=================================================================="

step() { printf '\n%s\n  %s\n%s\n' "$RULE" "$1" "$RULE"; }
fail() { printf '\n[ERROR] %s\n' "$1" >&2; exit 1; }

# --- Preconditions -----------------------------------------------------------

step "Step 0 - Checking preconditions"

command -v git >/dev/null 2>&1 || fail "git is not on PATH."
command -v python3 >/dev/null 2>&1 || fail "python3 is not on PATH."
command -v docker >/dev/null 2>&1 || fail "docker is not on PATH."
[ -n "$TOOL" ] && [ -f "$TOOL" ] || fail "main.py was not found above
        '$SCRIPT_DIR'. Run this script from inside the repository, or set
        TOOL to the path of main.py."

docker info >/dev/null 2>&1 || fail "No reachable Docker daemon. Both images are
        built and scanned, so the daemon is required. Run this under WSL2 or
        Linux: a daemon inside WSL2 is not reachable from a Windows Python
        interpreter."

docker buildx version >/dev/null 2>&1 || fail "docker buildx is unavailable. The
        build runs on BuildKit through 'docker buildx build'."

echo "  tool    : $TOOL"
echo "  report  : $REPORTS"
echo "  ok"

# --- Step 1: repository initialisation ---------------------------------------

step "Step 1 - Initialising the isolated repository"

rm -rf "$REPO"
mkdir -p "$REPO"
cd "$REPO"
git init -q
# Local to this throwaway repository; no global configuration is touched.
git config user.email "security-validation@local"
git config user.name "Security validation"
echo "  created $REPO"

# --- Step 2: the vulnerable state --------------------------------------------

step "Step 2 - Committing the 'before' state on $IMAGE_BEFORE"

printf 'console.log("App running");\n' > app.js

cat > Dockerfile <<DOCKERFILE
FROM $IMAGE_BEFORE
WORKDIR /app
COPY . .
CMD ["node", "app.js"]
DOCKERFILE

git add .
git commit -q -m "chore: initial state on the Debian base ($IMAGE_BEFORE)"
echo "  $(git rev-parse HEAD)  $(git log -1 --pretty=%s)"

# --- Step 3: the refactoring -------------------------------------------------

step "Step 3 - Committing the 'after' state on $IMAGE_AFTER"

cat > Dockerfile <<DOCKERFILE
FROM $IMAGE_AFTER
WORKDIR /app
COPY . .
CMD ["node", "app.js"]
DOCKERFILE

git add .
git commit -q -m "refactor(dockerfile): move to the Alpine base ($IMAGE_AFTER) to reduce the vulnerability surface"
echo "  $(git rev-parse HEAD)  $(git log -1 --pretty=%s)"

echo
echo "  The two states differ in the FROM tag and in nothing else:"
git --no-pager diff HEAD~1 HEAD -- Dockerfile | sed -n '/^[-+][^-+]/p' | sed 's/^/    /'

# --- Step 4: running the prototype -------------------------------------------

step "Step 4 - Running the prototype over HEAD~1..HEAD"

mkdir -p "$REPORTS"
echo "  Building and scanning both images. On a cold cache this pulls around"
echo "  1 GB and takes several minutes."
echo

python3 "$TOOL" "$REPO" HEAD~1 HEAD -o "$REPORTS" \
    2>&1 | tee "$REPORTS/terminal_output.log"

status="${PIPESTATUS[0]}"
printf 'EXIT=%s\n' "$status" >> "$REPORTS/terminal_output.log"
[ "$status" -eq 0 ] || fail "The tool exited with code $status. See $REPORTS/terminal_output.log"

# The two artefacts the committee is asked to inspect must both be present.
for required in "$REPORTS/impact_report.json" "$REPORTS/raw_data/trivy_raw.json"; do
    [ -s "$required" ] || fail "Expected artefact missing or empty: $required"
done

# --- Step 5: pointing the committee at the evidence --------------------------

step "Step 5 - Where to inspect the result"

python3 - "$REPORTS/impact_report.json" <<'SUMMARY'
import json
import sys

report = json.loads(open(sys.argv[1], encoding="utf-8").read())
cves = report["metrics"]["cves"]

rules = ", ".join(
    f"{entry['refactoring_id']} ({entry['refactoring_name']})"
    for entry in report["refactorings_detected"]
) or "none"
print(f"  Refactoring detected : {rules}")
print(f"  CVEs before          : {cves['before']}")
print(f"  CVEs after           : {cves['after']}")
print(f"  Delta                : {cves['delta_cves']:+d}")

stratified = cves.get("by_severity") or {}
before, after = stratified.get("before", {}), stratified.get("after", {})
delta = stratified.get("delta", {})
if delta:
    print()
    print(f"  {'severity':<10}{'before':>10}{'after':>10}{'delta':>10}")
    for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"):
        if severity not in delta:
            continue
        print(
            f"  {severity:<10}{before.get(severity, 0):>10}"
            f"{after.get(severity, 0):>10}{delta[severity]:>+10}"
        )
SUMMARY

cat <<REFERENCES

  The two files to open, in full:

    $REPORTS/impact_report.json
        The structured result. 'metrics.cves' carries the counts before and
        after, the delta, and its stratification by severity; the deltas for
        size, warnings and logical instructions sit alongside it, and
        'environment' records the version of every tool that produced them.

    $REPORTS/raw_data/trivy_raw.json
        Trivy's output exactly as emitted, never re-serialised. Every
        vulnerability counted above appears here with its identifier and
        severity, so any figure in the structured report can be traced back
        to the scanner that produced it.

  Also written:

    $REPORTS/human_readable_summary.txt   the report as printed above
    $REPORTS/terminal_output.log          this run, verbatim
    $REPORTS/raw_data/hadolint_raw.json   the linter output

  The scratch repository, kept only for inspection, is at
  $REPO
  It lives outside the working directory and is rebuilt from scratch on
  every run.

REFERENCES
