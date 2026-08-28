#!/usr/bin/env python3
"""Mechanical record-building for a systematic literature review.

Parses three database exports (IEEE Xplore CSV, Springer Link CSV, ACM
BibTeX), normalises them into a common schema, assigns sequential record
ids, writes an identified-records file with EVERY record, and flags
cross-database duplicates by DOI (primary) and normalised title (fallback).

This script makes NO inclusion/exclusion decisions. It only parses,
normalises, and flags. Screening is done manually by the reviewer.
"""

import csv
import os
import re
import sys

# --- paths -----------------------------------------------------------------
# The export files live in the repo root; all outputs stay inside
# literature-review/ so nothing else in the repo is touched.
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

IEEE_CSV = os.path.join(ROOT, "SearchResults IEEE.csv")
SPRINGER_CSV = os.path.join(ROOT, "Spring link Results.csv")
ACM_BIB = os.path.join(ROOT, "acm.bib")

OUT_IDENTIFIED = os.path.join(HERE, "identified-records.csv")
OUT_DUPLICATES = os.path.join(HERE, "duplicates.csv")
OUT_SEARCHLOG = os.path.join(HERE, "search-log.csv")

# Reported search-engine result counts (supplied by the reviewer). These are
# what each database reported for the query, independent of how many records
# actually appear in the export file.
SEARCH_LOG_COUNTS = {"IEEE": 241, "ACM": 20, "Springer": 12}


# --- normalisation helpers -------------------------------------------------
def clean(value):
    """Collapse whitespace and strip a single field value."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def norm_doi(doi):
    """Lowercased, trimmed DOI with any URL/`doi:` prefix removed."""
    d = clean(doi).lower()
    if not d:
        return ""
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    return d.strip()


def norm_title(title):
    """Lowercase; strip punctuation and whitespace for fuzzy title matching."""
    t = clean(title).lower()
    t = re.sub(r"[^a-z0-9]+", "", t)
    return t


# --- IEEE Xplore CSV -------------------------------------------------------
def parse_ieee(path):
    records = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            title = clean(row.get("Document Title"))
            if not title:
                continue  # skip fully blank trailing lines
            records.append(
                {
                    "title": title,
                    "authors": clean(row.get("Authors")),
                    "year": clean(row.get("Publication Year")),
                    "source": clean(row.get("Publication Title")),
                    "doi": clean(row.get("DOI")),
                    "url": "",
                    "database": "IEEE",
                }
            )
    return records


# --- Springer Link CSV -----------------------------------------------------
def parse_springer(path):
    records = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            title = clean(row.get("Item Title"))
            if not title:
                continue
            records.append(
                {
                    "title": title,
                    "authors": clean(row.get("Authors")),
                    "year": clean(row.get("Publication Year")),
                    "source": clean(row.get("Publication Title")),
                    "doi": clean(row.get("Item DOI")),
                    "url": clean(row.get("URL")),
                    "database": "Springer",
                }
            )
    return records


# --- ACM BibTeX ------------------------------------------------------------
def _split_bib_entries(text):
    """Yield (entry_type, body) for each @type{...} entry, brace-matched."""
    i, n = 0, len(text)
    while i < n:
        at = text.find("@", i)
        if at == -1:
            break
        brace = text.find("{", at)
        if brace == -1:
            break
        entry_type = text[at + 1 : brace].strip().lower()
        # walk to the matching closing brace
        depth, j = 0, brace
        while j < n:
            c = text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = text[brace + 1 : j]
        yield entry_type, body
        i = j + 1


def _parse_bib_fields(body):
    """Parse `key = {value}` / `key = "value"` / `key = value` pairs."""
    fields = {}
    # drop the citation key (up to first comma)
    comma = body.find(",")
    body = body[comma + 1 :] if comma != -1 else body
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
            value = body[j + 1 : k]
            i = k + 1
        elif body[j] == '"':
            k = j + 1
            while k < n and body[k] != '"':
                k += 1
            value = body[j + 1 : k]
            i = k + 1
        else:
            k = j
            while k < n and body[k] != ",":
                k += 1
            value = body[j:k]
            i = k
        if key:
            fields[key] = _delatex(value)
        # advance past trailing comma
        nxt = body.find(",", i)
        i = nxt + 1 if nxt != -1 else n
    return fields


def _delatex(value):
    """Best-effort cleanup of common BibTeX/LaTeX escapes and braces."""
    v = value
    # accented forms like \"{o}, \'{e}, \`{a}, \^{o}, \~{n}
    v = re.sub(r'\\[\'"`^~=.]\{?([a-zA-Z])\}?', r"\1", v)
    v = v.replace("\\&", "&").replace("~", " ")
    v = v.replace("{", "").replace("}", "")
    return clean(v)


def parse_acm(path):
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    records = []
    for entry_type, body in _split_bib_entries(text):
        f = _parse_bib_fields(body)
        title = clean(f.get("title"))
        if not title:
            continue
        source = clean(f.get("journal") or f.get("booktitle"))
        records.append(
            {
                "title": title,
                "authors": clean(f.get("author")),
                "year": clean(f.get("year")),
                "source": source,
                "doi": clean(f.get("doi")),
                "url": clean(f.get("url")),
                "database": "ACM",
            }
        )
    return records


# --- duplicate detection ---------------------------------------------------
def detect_duplicates(records):
    """Group records by normalised DOI, then by normalised title.

    Returns a list of duplicate rows (only for groups with >1 member),
    each pointing at the group's primary (earliest) record_id.
    """
    groups = {}  # key -> list of record indices
    for rec in records:
        d = norm_doi(rec["doi"])
        if d:
            key = ("doi", d)
        else:
            t = norm_title(rec["title"])
            key = ("title", t) if t else ("id", rec["record_id"])
        groups.setdefault(key, []).append(rec)

    dup_rows = []
    dup_group_count = 0
    dup_member_ids = set()
    for key, members in groups.items():
        if len(members) < 2:
            continue
        dup_group_count += 1
        primary = members[0]  # earliest record_id = canonical
        for rec in members:
            is_primary = rec is primary
            dup_member_ids.add(rec["record_id"])
            dup_rows.append(
                {
                    "record_id": rec["record_id"],
                    "title": rec["title"],
                    "doi": rec["doi"],
                    "database": rec["database"],
                    "duplicate_of": "" if is_primary else primary["record_id"],
                }
            )
    return dup_rows, dup_group_count, dup_member_ids


# --- main ------------------------------------------------------------------
def main():
    for path in (IEEE_CSV, SPRINGER_CSV, ACM_BIB):
        if not os.path.exists(path):
            sys.exit("Missing input file: %s" % path)

    ieee = parse_ieee(IEEE_CSV)
    springer = parse_springer(SPRINGER_CSV)
    acm = parse_acm(ACM_BIB)

    # IEEE first, then ACM, then Springer; sequential ids across all.
    records = ieee + acm + springer
    for idx, rec in enumerate(records, start=1):
        rec["record_id"] = "R%03d" % idx

    # identified-records.csv -- EVERY record, nothing removed.
    with open(OUT_IDENTIFIED, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["record_id", "title", "authors", "source", "year",
             "doi_or_url", "database"]
        )
        for rec in records:
            doi_or_url = rec["doi"] or rec["url"]
            writer.writerow(
                [rec["record_id"], rec["title"], rec["authors"],
                 rec["source"], rec["year"], doi_or_url, rec["database"]]
            )

    # duplicates.csv -- flagged only, never deleted.
    dup_rows, dup_group_count, dup_member_ids = detect_duplicates(records)
    with open(OUT_DUPLICATES, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["record_id", "title", "doi", "database", "duplicate_of"]
        )
        for r in dup_rows:
            writer.writerow(
                [r["record_id"], r["title"], r["doi"],
                 r["database"], r["duplicate_of"]]
            )

    # search-log.csv -- reviewer fills query/date; counts are supplied.
    with open(OUT_SEARCHLOG, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["database", "query", "execution_date", "results_count"]
        )
        for db in ("IEEE", "ACM", "Springer"):
            writer.writerow([db, "<QUERY>", "<DATE>", SEARCH_LOG_COUNTS[db]])

    # summary
    total = len(records)
    unique_after_dedup = total - (len(dup_member_ids) - dup_group_count)
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("Records parsed per database:")
    print("  IEEE     : %d  (search-log reported %d)"
          % (len(ieee), SEARCH_LOG_COUNTS["IEEE"]))
    print("  ACM      : %d  (search-log reported %d)"
          % (len(acm), SEARCH_LOG_COUNTS["ACM"]))
    print("  Springer : %d  (search-log reported %d)"
          % (len(springer), SEARCH_LOG_COUNTS["Springer"]))
    print("-" * 60)
    print("Total records identified : %d" % total)
    print("Duplicate groups         : %d" % dup_group_count)
    print("Records flagged as dup   : %d" % len(dup_member_ids))
    print("Unique records after dedup: %d" % unique_after_dedup)
    print("=" * 60)


if __name__ == "__main__":
    main()
