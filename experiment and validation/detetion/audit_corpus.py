"""Audit the batch results in execution_artifacts/ against the corpus specification.

Reads `mapping.md`, the human-readable specification of the corpus, and for each
pair it defines compares the rules the tool reported in that pair's
`impact_report.json` against the rules the specification lists.

Three checks, one per case class, plus one that applies to all of them:

    Canonical            every listed rule must be reported
    False-negative test  every listed rule must be reported
    Mixed                every listed rule must be reported
    False-positive test  no listed rule may be reported

    all classes          no rule outside the pair's list may be reported

A rule the specification lists and the tool did not report is a FALSE NEGATIVE.
A forbidden rule the tool did report is a FALSE POSITIVE. A rule reported that
the pair does not cite at all is an UNLISTED DETECTION. All three are errors:
a pair conforms only when the set of rules reported is exactly the set the
specification calls for.
"""

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_MAPPING = PROJECT_ROOT / "mapping.md"
DEFAULT_ARTIFACTS = PROJECT_ROOT / "execution_artifacts"
REPORT_NAME = "impact_report.json"

# Case classes as `mapping.md` spells them, and what each demands.
MUST_REPORT = ("Canonical", "False-negative test", "Mixed")
MUST_NOT_REPORT = ("False-positive test",)

FALSE_NEGATIVE = "FALSE NEGATIVE"
FALSE_POSITIVE = "FALSE POSITIVE"
UNLISTED = "UNLISTED DETECTION"

HEADING = re.compile(r"^###\s+Pair\s+(\d+)\s*$")
FIELD = re.compile(r"^-\s+\*\*(?P<name>[^:*]+):\*\*\s*(?P<value>.*?)\s*$")
RULE = re.compile(r"R\d{2}")

WIDE = "=" * 98
THIN = "-" * 98


class AuditError(Exception):
    """The audit cannot be carried out on the material given."""


def parse_mapping(path: Path) -> list:
    """The pairs `mapping.md` defines, in the order it defines them.

    Parsed from the per-pair sections rather than the index table: the sections
    are the specification proper, the table restates them for reading.
    """
    try:
        lines = path.read_text(encoding="utf-8").split("\n")
    except OSError as exc:
        raise AuditError(f"Could not read {path}: {exc}") from exc

    pairs, current = [], None
    for line in lines:
        heading = HEADING.match(line)
        if heading:
            current = {"index": int(heading.group(1))}
            pairs.append(current)
            continue
        if current is None:
            continue  # preamble and index table, before the first pair
        field = FIELD.match(line)
        if field:
            current[field.group("name").strip().lower()] = field.group("value")

    if not pairs:
        raise AuditError(
            f"{path} defines no pairs. Expected sections headed '### Pair <n>'."
        )

    specification = []
    for entry in pairs:
        index = entry["index"]
        case_type = entry.get("case type", "").strip()
        if case_type not in MUST_REPORT + MUST_NOT_REPORT:
            raise AuditError(
                f"Pair {index} in {path} carries an unknown case type: "
                f"{case_type!r}. Known: {', '.join(MUST_REPORT + MUST_NOT_REPORT)}."
            )
        specification.append(
            {
                "index": index,
                "case_type": case_type,
                "artifact": entry.get("artifact", "").strip("` "),
                "rules": set(RULE.findall(entry.get("rules", ""))),
            }
        )

    seen = [entry["index"] for entry in specification]
    if seen != sorted(seen) or len(set(seen)) != len(seen):
        raise AuditError(f"{path} numbers its pairs out of order or repeats one.")
    return specification


def reported_rules(report_file: Path) -> set:
    """The refactoring identifiers the tool recorded for one pair."""
    import json

    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuditError(f"Could not read {report_file}: {exc}") from exc
    entries = report.get("refactorings_detected")
    if entries is None:
        raise AuditError(f"{report_file} carries no 'refactorings_detected' section.")
    return {entry["refactoring_id"] for entry in entries}


def audit_pair(spec: dict, artifacts: Path) -> dict:
    """Judge one pair against what its case class demands."""
    index = spec["index"]
    report_file = artifacts / f"pair_{index}" / REPORT_NAME
    if not report_file.is_file():
        raise AuditError(f"No report for pair_{index}: {report_file} is missing.")

    expected = spec["rules"]
    detected = reported_rules(report_file)

    outcome = {
        **spec,
        "expected": sorted(expected),
        "detected": sorted(detected),
        "missing": [],
        "forbidden": [],
        "unlisted": sorted(detected - expected),
        "errors": [],
    }

    if spec["case_type"] in MUST_REPORT:
        outcome["missing"] = sorted(expected - detected)
    else:
        outcome["forbidden"] = sorted(expected & detected)

    if outcome["missing"]:
        outcome["errors"].append(FALSE_NEGATIVE)
    if outcome["forbidden"]:
        outcome["errors"].append(FALSE_POSITIVE)
    if outcome["unlisted"]:
        outcome["errors"].append(UNLISTED)

    outcome["passes"] = not outcome["errors"]
    return outcome


def verdict_of(outcome: dict) -> str:
    parts = []
    if outcome["missing"]:
        parts.append(f"{FALSE_NEGATIVE}: {','.join(outcome['missing'])} not reported")
    if outcome["forbidden"]:
        parts.append(f"{FALSE_POSITIVE}: {','.join(outcome['forbidden'])} reported")
    if outcome["unlisted"]:
        parts.append(f"{UNLISTED}: {','.join(outcome['unlisted'])} not in the pair")
    return "; ".join(parts) if parts else "pass"


def print_pairs(outcomes: list) -> None:
    print(THIN)
    print(f"{'pair':>5}  {'case class':20}  {'specified':22}  {'reported':24}  verdict")
    print(THIN)
    for outcome in outcomes:
        print(
            f"{outcome['index']:>5}  {outcome['case_type']:20}  "
            f"{','.join(outcome['expected']) or '-':22}  "
            f"{','.join(outcome['detected']) or '-':24}  {verdict_of(outcome)}"
        )
    print(THIN)


def print_summary(outcomes: list) -> None:
    total = len(outcomes)
    passing = [o for o in outcomes if o["passes"]]
    by_error = {
        name: [o for o in outcomes if name in o["errors"]]
        for name in (FALSE_NEGATIVE, FALSE_POSITIVE, UNLISTED)
    }

    print()
    print(WIDE)
    print("CONSOLIDATED SUMMARY")
    print(WIDE)
    print(f"pairs audited : {total}")
    print()

    print("By case class")
    for case_type in MUST_REPORT + MUST_NOT_REPORT:
        subset = [o for o in outcomes if o["case_type"] == case_type]
        if not subset:
            continue
        demand = (
            "listed rules must be reported"
            if case_type in MUST_REPORT
            else "listed rule must NOT be reported"
        )
        passed = sum(1 for o in subset if o["passes"])
        print(f"  {case_type:22} {passed:>3}/{len(subset):<3}  ({demand}; nothing else)")
    print()

    print("Errors")
    labels = {
        FALSE_NEGATIVE: ("false negatives", "missing", "not reported"),
        FALSE_POSITIVE: ("false positives", "forbidden", "reported"),
        UNLISTED: ("unlisted detections", "unlisted", "not cited by the pair"),
    }
    for name, (heading, key, tail) in labels.items():
        affected = by_error[name]
        print(f"  {heading:22}: {len(affected)}")
        for outcome in affected:
            print(f"      pair_{outcome['index']}: {','.join(outcome[key])} {tail}")
    print()

    print("Rate")
    print(THIN)
    print(
        f"  success rate : {len(passing)}/{total} ({len(passing) / total:.1%})"
        f"   the rules reported are exactly the rules specified"
    )
    print(THIN)


def parse_arguments(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit the per-pair reports in execution_artifacts/ against the "
            "corpus specification in mapping.md."
        )
    )
    parser.add_argument(
        "-m",
        "--mapping",
        default=str(DEFAULT_MAPPING),
        help=f"path of mapping.md (default: {DEFAULT_MAPPING})",
    )
    parser.add_argument(
        "-a",
        "--artifacts",
        default=str(DEFAULT_ARTIFACTS),
        help=f"directory holding the pair_N folders (default: {DEFAULT_ARTIFACTS})",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="print the consolidated summary only, without the per-pair table",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    arguments = parse_arguments(argv)
    mapping_file = Path(arguments.mapping).expanduser()
    artifacts = Path(arguments.artifacts).expanduser()

    try:
        specification = parse_mapping(mapping_file)
        outcomes = [audit_pair(spec, artifacts) for spec in specification]
    except AuditError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(f"specification : {mapping_file}")
    print(f"artifacts     : {artifacts}")
    print()
    if not arguments.quiet:
        print_pairs(outcomes)
    print_summary(outcomes)

    return 0 if all(outcome["passes"] for outcome in outcomes) else 2


if __name__ == "__main__":
    sys.exit(main())
