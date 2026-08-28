# Systematic Literature Review — Replication Package

This folder contains the complete replication package for the systematic
literature review (SLR) reported in the dissertation *"Dockerfile
Refactorings: Detection and Effects"*. It provides every artefact needed for
an independent reviewer to re-derive the review's selection funnel from the
raw database exports, in line with the PRISMA 2020 guidelines.

The review follows a **two-arm PRISMA model**: a database arm (systematic
queries over IEEE Xplore, the ACM Digital Library, and Springer Link) and an
other-methods arm (targeted handsearching of authoritative, non-database
sources).

## Selection funnel (PRISMA)

```
Identified (databases)                     273   (IEEE 241 + ACM 20 + Springer 12)
  Duplicates removed                        -1   (R246, cross-database duplicate of R028)
  Phase 1 - Screening excluded            -175   (title/metadata level)
  Phase 2 - Eligibility excluded           -81   (title-level topical assessment)
  Included - database arm                   16
Other-methods arm (handsearching)          +5
                                          ----
Total included in review                    21
```

Phase 1 exclusions (175): 155 with no containerization/IaC context in the
title, 19 non-peer-reviewed items (commercial e-books, book chapters, one
standard), 1 proceedings front matter.

Phase 2 exclusions (81): 34 with no refactoring/smell/quality term, 25
competing Infrastructure-as-Code technologies (Ansible/Terraform/Puppet/Chef),
12 image vulnerability scanning, 5 cluster orchestration or CI/CD, 5 runtime
performance or resource use.

## Folder structure

```
literature-review/
├── SearchResults IEEE.csv        Raw export — IEEE Xplore (241 records)
├── Spring link Results.csv       Raw export — Springer Link (12 records)
├── acm.bib                       Raw export — ACM Digital Library (20 BibTeX entries)
└── Prisma/
    ├── build_records.py          Parses the three raw exports; builds identified-records + duplicates + search-log
    ├── screen.py                 Applies Phase 1 and Phase 2 screening; builds exclusion-log + included-studies
    ├── search-log.csv            Query, execution date, and result count per database
    ├── identified-records.csv    All 273 identified records (title, authors, source, year, DOI/URL, database)
    ├── duplicates.csv            Cross-database duplicate(s) flagged (not deleted)
    ├── exclusion-log.csv         Every excluded record with its stage and a title-grounded reason
    └── included-studies.csv      The 21 included studies (16 database + 5 handsearching) with metadata
```

## How to reproduce

Requirements: Python 3.8+ (standard library only — no external packages).

From inside the `Prisma/` folder:

```bash
python build_records.py     # reads the three raw exports, writes identified-records.csv,
                            # duplicates.csv, and the result counts of search-log.csv
python screen.py            # applies the screening rules, writes exclusion-log.csv
                            # and included-studies.csv (database arm)
```

`build_records.py` and `screen.py` expect the three raw export files to sit
in the parent folder (`literature-review/`), exactly as shipped here. They
write their outputs into the `Prisma/` folder.

> **Note on the handsearching arm.** The five handsearched sources
> (`search_arm = handsearching`, rows H001–H005 in `included-studies.csv`)
> are authoritative non-database sources identified outside the automated
> queries; they are added manually and are **not** produced by `screen.py`.
> Re-running `screen.py` regenerates the 16 database rows only, so the five
> handsearching rows must be re-appended afterwards if the script is run again.

## Screening method

Screening was performed at the **title and metadata level**, not on full
texts; each exclusion reason cites the metadata field or matched term it was
derived from, so every row is re-derivable from titles and metadata alone.

Inclusion in the database arm followed a single, uniformly applied topical
rule: a record is included if its title contains a Docker/container context
term together with a quality-related term (smell, refactoring, technical
debt, quality, lint, cleaner, multi-stage, static analysis, ecosystem,
reproducibility, or artifact). The same rule is applied to every record; no
per-record overrides are used.

## File schemas

- **search-log.csv** — `database, query, execution_date, results_count`
- **identified-records.csv** — `record_id, title, authors, source, year, doi_or_url, database`
- **duplicates.csv** — `record_id, title, doi, database, duplicate_of`
- **exclusion-log.csv** — `record_id, title, exclusion_stage, exclusion_reason`
- **included-studies.csv** — `record_id, title, authors, source, year, doi, url, search_arm, access_date`

## Search queries (executed 2026-07-11)

- **IEEE Xplore:** `("Dockerfile" AND ("refactoring" OR "smells")) OR ("Infrastructure as Code" AND "quality") OR ("Docker" AND "mining") OR ("Docker" AND "empirical study")`
- **ACM Digital Library:** `("Dockerfile" AND ("refactoring" OR "smells")) OR ("container" AND "technical debt") OR ("Docker" AND "reproducible research")`
- **Springer Link:** `title:"Dockerfile"` (Advanced Search, title field)
