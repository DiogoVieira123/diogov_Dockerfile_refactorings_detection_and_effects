#!/usr/bin/env python3
import json
from pathlib import Path

# Maps each PoC to its relevant Hadolint code (None = size/CVEs only)
HADOLINT_CODE = {
    "poc-1-inline-run": "DL3059",
    "poc-2-update-base-image-tag": "DL3007",
    "poc-3-update-base-image": None,
    "poc-4-replace-add-with-copy": "DL3020",
}

def count_code(path, code):
    data = json.load(open(path))
    return sum(1 for x in data if x.get("code") == code)

def count_cves(path):
    data = json.load(open(path))
    ids = set()
    for r in data.get("Results", []) or []:
        for v in r.get("Vulnerabilities", []) or []:
            ids.add(v.get("VulnerabilityID"))
    return len(ids)

def read_int(path):
    return int(open(path).read().strip())

for folder, code in HADOLINT_CODE.items():
    p = Path(folder)
    if not p.exists(): continue
    sb = read_int(p / "size-before.txt")
    sa = read_int(p / "size-after.txt")
    cb = count_cves(p / "trivy-before.json")
    ca = count_cves(p / "trivy-after.json")
    if code:
        hb = count_code(p / "hadolint-before.json", code)
        ha = count_code(p / "hadolint-after.json",  code)
        warn_row = f"| Hadolint {code} | {hb} | {ha} | {ha-hb:+d} |\n"
        warn_print = f"Delta {code}={ha-hb:+d}"
    else:
        warn_row = ""
        warn_print = "Delta Warnings=n/a"

    md = f"""# {folder} — deltas

| Metric | Before | After | Delta |
|---|---|---|---|
| Size (bytes) | {sb} | {sa} | {sa-sb:+d} |
{warn_row}| CVEs (unique) | {cb} | {ca} | {ca-cb:+d} |
"""
    (p / "deltas.md").write_text(md)
    print(f"{folder}: Delta Size={sa-sb:+d} bytes  {warn_print}  Delta CVEs={ca-cb:+d}")
