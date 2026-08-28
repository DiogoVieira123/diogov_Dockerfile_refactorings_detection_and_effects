#!/usr/bin/env python3
"""Full PRISMA screening pipeline for the systematic literature review.

Steps:
  1. Identification  - parse IEEE CSV, Springer CSV, ACM BibTeX ->
                       identified-records.csv (ALL records).
  2. Deduplication   - flag cross-database duplicates -> duplicates.csv;
                       remove non-canonical duplicates from the working set.
  3. Phase 1         - title/metadata screening on OBJECTIVE criteria only
                       (year >= 2015, English, peer-reviewed record type,
                       on-topic title). Excluded records go to
                       exclusion-log.csv with a real, specific reason.
  4. Phase 2         - single topical inclusion rule, applied uniformly:
                       title contains (docker|container) AND (smell|
                       refactor|debt|quality|lint|cleaner|multi-stage|
                       static analysis|ecosystem|reproduc|artifact).
                       Inclusion is tested BEFORE the thematic exclusion
                       buckets, so a rule-matching title can never fall
                       into an exclusion drawer. Matching papers ->
                       included-studies.csv. Non-matching survivors are
                       logged at "Phase 2 - Eligibility" with a title-level
                       thematic classification (security / performance /
                       orchestration / IaC / no rule terms).
  5. Search log      - search-log.csv with the real query strings.

Methodology note: the rule's keyword set was validated against a set of
known relevant studies (quasi-gold standard) and then applied uniformly to
the whole corpus with no per-record overrides. Every exclusion_reason
describes only what was actually checked (publication year, record type,
title terms). No reason claims a full-text evaluation, because none was
performed by this script.
"""

import csv
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

IEEE_CSV = os.path.join(ROOT, "SearchResults IEEE.csv")
SPRINGER_CSV = os.path.join(ROOT, "Spring link Results.csv")
ACM_BIB = os.path.join(ROOT, "acm.bib")

OUT_IDENTIFIED = os.path.join(HERE, "identified-records.csv")
OUT_DUPLICATES = os.path.join(HERE, "duplicates.csv")
OUT_EXCLUSION = os.path.join(HERE, "exclusion-log.csv")
OUT_INCLUDED = os.path.join(HERE, "included-studies.csv")
OUT_SEARCHLOG = os.path.join(HERE, "search-log.csv")

ACCESS_DATE = "2026-07-11"
YEAR_CUTOFF = 2015


# IEEE "Document Identifier" values that are not peer-reviewed research
# venues (verified against the actual export).
IEEE_NON_PEER_REVIEWED = {
    "Manning eBooks": "Commercial eBook (Manning), not peer-reviewed",
    "Packt Publishing eBooks": "Commercial eBook (Packt), not peer-reviewed",
    "Wiley-IEEE Press eBook Chapters":
        "Book chapter (Wiley-IEEE Press eBook), not peer-reviewed",
    "Wiley AI eBook Chapters":
        "Book chapter (Wiley AI eBook), not peer-reviewed",
    "IEEE Standards":
        "Standards document (IEEE Standard), not a peer-reviewed study",
}

# Springer "Content Type" values that are not peer-reviewed articles.
SPRINGER_NON_PEER_REVIEWED = {
    "Chapter": "Book chapter (Springer Content Type: Chapter), "
               "not a peer-reviewed article",
    "Video segment": "Video segment (Springer Content Type: Video segment), "
                     "not a peer-reviewed publication",
}

# Phase 1 container-context terms: a record is excluded as off-topic only
# if its title contains NONE of these (docker also matches dockerfile/
# dockerignore; spelled-out "infrastructure as code" counts as IaC).
ON_TOPIC_PATTERN = re.compile(
    r"docker|container|kubernetes|ansible|terraform|puppet|\bchef\b|"
    r"\biac\b|infrastructure[ -]as[ -]code",
    re.IGNORECASE,
)

SEARCH_LOG_ROWS = [
    ("IEEE",
     '("Dockerfile" AND ("refactoring" OR "smells")) OR '
     '("Infrastructure as Code" AND "quality") OR '
     '("Docker" AND "mining") OR ("Docker" AND "empirical study")',
     "2026-07-11", 241),
    ("ACM",
     '("Dockerfile" AND ("refactoring" OR "smells")) OR '
     '("container" AND "technical debt") OR '
     '("Docker" AND "reproducible research")',
     "2026-07-11", 20),
    ("Springer", 'title:"Dockerfile"', "2026-07-11", 12),
]

# --- Handsearching arm (studies identified via other methods) -----------------
# Reviewer-supplied grey-literature sources, appended to included-studies.csv
# with search_arm="handsearching". Fields left "" were not supplied and must
# be completed by the reviewer (the script warns about them); no bibliographic
# detail is invented here.
# Tuples: (record_id, title, authors, source, year, doi, url)
HANDSEARCHING_RECORDS = [
    ("H001", "", "Martin Fowler", "martinfowler.com", "2018", "", ""),
    ("H002", "", "CNCF", "Cloud Native Computing Foundation", "2024", "",
     ""),
    ("H003", "Docker Best Practices", "Docker Docs",
     "Docker Documentation", "2026", "",
     "https://docs.docker.com/build/building/best-practices/"),
    ("H004", "Multi-stage builds", "Docker Docs",
     "Docker Documentation", "2026", "",
     "https://docs.docker.com/build/building/multi-stage/"),
    ("H005", "Hadolint: Dockerfile Linter", "Hadolint contributors",
     "GitHub", "2026", "", "https://github.com/hadolint/hadolint"),
]

# --- Phase 2 topical inclusion rule -------------------------------------------
# A Phase-1 survivor is INCLUDED iff its title matches BOTH patterns.
# This is the single, uniformly applied eligibility criterion; there is no
# per-record whitelist. The inclusion test runs BEFORE the exclusion
# buckets, so a rule-matching title never falls into a thematic drawer.
PHASE2_TOPIC = re.compile(r"docker|container", re.IGNORECASE)
PHASE2_QUALITY = re.compile(
    r"smell|refactor|debt|quality|lint|cleaner|multi-?stage|"
    r"static analysis|ecosystem|reproduc|artifact",
    re.IGNORECASE,
)


def phase2_rule_match(title):
    return bool(PHASE2_TOPIC.search(title) and PHASE2_QUALITY.search(title))

# Thematic buckets, applied in this order to the remaining candidates.
# Each reason is grounded in the title: it names the matched term(s) and
# claims only what the title indicates.
_CATALOG_TAIL = (
    "title does not satisfy the Phase 2 topical inclusion rule (no "
    "smell/refactoring/quality/linting/ecosystem/reproducibility/artifact "
    "term alongside a Docker or container context)."
)
PHASE2_BUCKETS = [
    ("security",
     re.compile(r"security|vulnerab|leak|secret|attack|privilege", re.I),
     "title indicates a focus on container/IaC security scanning, "
     "vulnerability diagnostics, or secret-leak mitigation; "),
    ("performance",
     re.compile(r"performance|runtime|network|benchmark|\bhpc\b|resource|"
                r"energy", re.I),
     "title indicates a focus on container runtime performance, networking, "
     "benchmarking, or resource utilization; "),
    ("orchestration",
     re.compile(r"kubernetes|orchestrat|swarm|cluster|deployment|devops|"
                r"pipeline", re.I),
     "title indicates a focus on cluster orchestration, container "
     "deployment workflows, or DevOps/CI-CD pipeline infrastructure; "),
    ("iac",
     re.compile(r"ansible|terraform|puppet|\bchef\b|"
                r"infrastructure[ -]as[ -]code|\biac\b", re.I),
     "title indicates a focus on general Infrastructure-as-Code "
     "(Ansible/Terraform/Puppet/Chef/IaC) configuration quality rather "
     "than a Dockerfile-specific catalog; "),
]

PHASE2_OTHER_REASON = (
    "Exclusion Criterion (title-level screening): " + _CATALOG_TAIL[0].upper()
    + _CATALOG_TAIL[1:]
)


def classify_phase2(title):
    """Return (bucket_name, truthful title-grounded exclusion reason)."""
    for name, pattern, theme in PHASE2_BUCKETS:
        matches = sorted(set(m.group(0).lower()
                             for m in pattern.finditer(title)))
        if matches:
            reason = (
                "Exclusion Criterion (title-level screening; matched "
                "term(s): %s): %s%s" % (", ".join(matches), theme,
                                        _CATALOG_TAIL)
            )
            return name, reason
    return "no-catalog-indicated", PHASE2_OTHER_REASON


# --- shared normalisation helpers -------------------------------------------
def clean(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def norm_doi(doi):
    d = clean(doi).lower()
    if not d:
        return ""
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    return d.strip()


def norm_title(title):
    return re.sub(r"[^a-z0-9]+", "", clean(title).lower())


def non_english(title):
    """Objective heuristic: mostly non-ASCII letters -> likely not English."""
    letters = [c for c in title if c.isalpha()]
    if not letters:
        return False
    non_ascii = sum(1 for c in letters if ord(c) > 127)
    return non_ascii / len(letters) > 0.3


# --- Step 1: parsing ---------------------------------------------------------
def parse_ieee(path):
    records = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            title = clean(row.get("Document Title"))
            if not title:
                continue
            records.append({
                "title": title,
                "authors": clean(row.get("Authors")),
                "year": clean(row.get("Publication Year")),
                "source": clean(row.get("Publication Title")),
                "doi": clean(row.get("DOI")),
                "url": "",
                "database": "IEEE",
                "record_type": clean(row.get("Document Identifier")),
            })
    return records


def parse_springer(path):
    records = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            title = clean(row.get("Item Title"))
            if not title:
                continue
            records.append({
                "title": title,
                "authors": clean(row.get("Authors")),
                "year": clean(row.get("Publication Year")),
                "source": clean(row.get("Publication Title")),
                "doi": clean(row.get("Item DOI")),
                "url": clean(row.get("URL")),
                "database": "Springer",
                "record_type": clean(row.get("Content Type")),
            })
    return records


def _split_bib_entries(text):
    i, n = 0, len(text)
    while i < n:
        at = text.find("@", i)
        if at == -1:
            break
        brace = text.find("{", at)
        if brace == -1:
            break
        entry_type = text[at + 1:brace].strip().lower()
        depth, j = 0, brace
        while j < n:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield entry_type, text[brace + 1:j]
        i = j + 1


def _delatex(value):
    v = re.sub(r'\\[\'"`^~=.]\{?([a-zA-Z])\}?', r"\1", value)
    v = v.replace("\\&", "&").replace("~", " ")
    return clean(v.replace("{", "").replace("}", ""))


def _parse_bib_fields(body):
    fields = {}
    comma = body.find(",")
    body = body[comma + 1:] if comma != -1 else body
    i, n = 0, len(body)
    while i < n:
        eq = body.find("=", i)
        if eq == -1:
            break
        key = body[i:eq].strip().strip(",").lower()
        j = eq + 1
        while j < n and body[j] in " \t\r\n":
            j += 1
        if j >= n:
            break
        if body[j] == "{":
            depth, k = 0, j
            while k < n:
                if body[k] == "{":
                    depth += 1
                elif body[k] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            value, i = body[j + 1:k], k + 1
        elif body[j] == '"':
            k = j + 1
            while k < n and body[k] != '"':
                k += 1
            value, i = body[j + 1:k], k + 1
        else:
            k = j
            while k < n and body[k] != ",":
                k += 1
            value, i = body[j:k], k
        if key:
            fields[key] = _delatex(value)
        nxt = body.find(",", i)
        i = nxt + 1 if nxt != -1 else n
    return fields


def parse_acm(path):
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    records = []
    for entry_type, body in _split_bib_entries(text):
        f = _parse_bib_fields(body)
        title = clean(f.get("title"))
        if not title:
            continue
        records.append({
            "title": title,
            "authors": clean(f.get("author")),
            "year": clean(f.get("year")),
            "source": clean(f.get("journal") or f.get("booktitle")),
            "doi": clean(f.get("doi")),
            "url": clean(f.get("url")),
            "database": "ACM",
            "record_type": entry_type,  # article / inproceedings / proceedings
        })
    return records


# --- Step 2: deduplication ---------------------------------------------------
def detect_duplicates(records):
    groups = {}
    for rec in records:
        d = norm_doi(rec["doi"])
        key = ("doi", d) if d else ("title", norm_title(rec["title"]))
        groups.setdefault(key, []).append(rec)

    dup_rows, removed_ids = [], set()
    for members in groups.values():
        if len(members) < 2:
            continue
        primary = members[0]
        for rec in members:
            dup_rows.append({
                "record_id": rec["record_id"],
                "title": rec["title"],
                "doi": rec["doi"],
                "database": rec["database"],
                "duplicate_of": "" if rec is primary else primary["record_id"],
            })
            if rec is not primary:
                removed_ids.add(rec["record_id"])
    return dup_rows, removed_ids


# --- Step 3: Phase 1 objective screening --------------------------------------
def phase1_reason(rec):
    """Return a specific exclusion reason, or None if the record survives.

    Only objective, actually-checked properties are used; the reason text
    states exactly what was checked.
    """
    year_str = rec["year"]
    if year_str.isdigit() and int(year_str) < YEAR_CUTOFF:
        return "Published %s, before the %d cutoff" % (year_str, YEAR_CUTOFF)

    if non_english(rec["title"]):
        return "Title predominantly non-English (language criterion)"

    rt = rec["record_type"]
    if rec["database"] == "IEEE" and rt in IEEE_NON_PEER_REVIEWED:
        return IEEE_NON_PEER_REVIEWED[rt]
    if rec["database"] == "Springer" and rt in SPRINGER_NON_PEER_REVIEWED:
        return SPRINGER_NON_PEER_REVIEWED[rt]
    if rec["database"] == "ACM" and rt == "proceedings":
        return ("Proceedings volume front matter (BibTeX @proceedings), "
                "not a peer-reviewed study")

    if not ON_TOPIC_PATTERN.search(rec["title"]):
        return ("Off-topic: title lacks containerization/IaC context "
                "(no Docker/Dockerfile, container, Kubernetes, IaC, "
                "Ansible, Terraform, Puppet, or Chef terms)")
    return None


# --- main ---------------------------------------------------------------------
def main():
    # Step 1: identification
    records = parse_ieee(IEEE_CSV) + parse_acm(ACM_BIB) + parse_springer(SPRINGER_CSV)
    for idx, rec in enumerate(records, start=1):
        rec["record_id"] = "R%03d" % idx
    by_id = {r["record_id"]: r for r in records}

    with open(OUT_IDENTIFIED, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["record_id", "title", "authors", "source", "year",
                    "doi_or_url", "database"])
        for r in records:
            w.writerow([r["record_id"], r["title"], r["authors"], r["source"],
                        r["year"], r["doi"] or r["url"], r["database"]])

    # Step 2: deduplication
    dup_rows, removed_ids = detect_duplicates(records)
    with open(OUT_DUPLICATES, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["record_id", "title", "doi", "database", "duplicate_of"])
        for r in dup_rows:
            w.writerow([r["record_id"], r["title"], r["doi"], r["database"],
                        r["duplicate_of"]])
    working = [r for r in records if r["record_id"] not in removed_ids]

    # Step 3: Phase 1 objective screening
    phase1_excluded, phase1_survivors = [], []
    for rec in working:
        reason = phase1_reason(rec)
        if reason:
            phase1_excluded.append((rec, reason))
        else:
            phase1_survivors.append(rec)

    # Step 4: Phase 2 eligibility -- single topical rule, applied uniformly
    included = [r for r in phase1_survivors
                if phase2_rule_match(r["title"])]
    included_ids = {r["record_id"] for r in included}

    phase2_rows = []  # (rec, bucket, reason)
    for rec in phase1_survivors:
        if rec["record_id"] in included_ids:
            continue
        bucket, reason = classify_phase2(rec["title"])
        phase2_rows.append((rec, bucket, reason))

    with open(OUT_EXCLUSION, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["record_id", "title", "exclusion_stage",
                    "exclusion_reason"])
        for rec, reason in phase1_excluded:
            w.writerow([rec["record_id"], rec["title"],
                        "Phase 1 - Screening", reason])
        for rec, bucket, reason in phase2_rows:
            w.writerow([rec["record_id"], rec["title"],
                        "Phase 2 - Eligibility", reason])

    with open(OUT_INCLUDED, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["record_id", "title", "authors", "source", "year",
                    "doi", "url", "search_arm", "access_date"])
        for r in included:
            url = r["url"] or ("https://doi.org/%s" % r["doi"]
                               if r["doi"] else "")
            w.writerow([r["record_id"], r["title"], r["authors"], r["source"],
                        r["year"], r["doi"], url, "database", ACCESS_DATE])
        for (hid, title, authors, source, year, doi,
             url) in HANDSEARCHING_RECORDS:
            w.writerow([hid, title, authors, source, year, doi, url,
                        "handsearching", ACCESS_DATE])

    # Step 5: search log
    with open(OUT_SEARCHLOG, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["database", "query", "execution_date", "results_count"])
        for row in SEARCH_LOG_ROWS:
            w.writerow(row)

    # summary
    print("=" * 64)
    print("PRISMA SCREENING SUMMARY")
    print("=" * 64)
    print("Step 1  Identified                     : %d" % len(records))
    print("Step 2  Duplicates removed             : %d" % len(removed_ids))
    print("Step 3  Phase 1 excluded (objective)   : %d" % len(phase1_excluded))
    print("Step 4  Phase 2 excluded (title-level) : %d" % len(phase2_rows))
    print("Step 4  Included via databases         : %d" % len(included))
    print("        Included via handsearching     : %d"
          % len(HANDSEARCHING_RECORDS))
    print("        TOTAL included studies         : %d"
          % (len(included) + len(HANDSEARCHING_RECORDS)))
    print("-" * 64)
    print("check: %d dup + %d P1 + %d P2 + %d included = %d"
          % (len(removed_ids), len(phase1_excluded), len(phase2_rows),
             len(included),
             len(removed_ids) + len(phase1_excluded) + len(phase2_rows)
             + len(included)))
    print()
    print("Phase 1 exclusions by reason:")
    counts = {}
    for _, reason in phase1_excluded:
        counts[reason] = counts.get(reason, 0) + 1
    for reason, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print("  %3d  %s" % (n, reason))
    print()
    print("Phase 2 exclusions by title-level bucket:")
    bcounts = {}
    for _, bucket, _ in phase2_rows:
        bcounts[bucket] = bcounts.get(bucket, 0) + 1
    for bucket, n in sorted(bcounts.items(), key=lambda kv: -kv[1]):
        print("  %3d  %s" % (n, bucket))
    print()
    print("Included studies (topical rule: (docker|container) AND "
          "(smell|refactor|")
    print("debt|quality|lint|cleaner|multi-stage|static analysis|"
          "ecosystem|reproduc|artifact)):")
    for r in included:
        terms = sorted(set(m.group(0).lower()
                           for m in PHASE2_QUALITY.finditer(r["title"])))
        print("  %s  [%s]  %s"
              % (r["record_id"], ", ".join(terms), r["title"]))
    print()
    print("Handsearching arm (%d records):" % len(HANDSEARCHING_RECORDS))
    incomplete = []
    for (hid, title, authors, source, year, doi,
         url) in HANDSEARCHING_RECORDS:
        print("  %s  %s (%s)  %s" % (hid, authors, year, title or "--"))
        if not title or not url:
            incomplete.append(hid)
    if incomplete:
        print()
        print("WARNING: handsearching record(s) %s are missing title and/or"
              % ", ".join(incomplete))
        print("URL. Complete these fields in HANDSEARCHING_RECORDS with the")
        print("exact source you consulted before citing them in the review.")
    print("=" * 64)


if __name__ == "__main__":
    main()
