#!/usr/bin/env python3
"""Check scene tags against taxonomy.json.

    python3 tools/validate.py                     # every scene in catalog/*.json
    python3 tools/validate.py --tags FILE.json    # a JSON list of tag records (must each have "id")

Exits non-zero and lists every problem when a value is unknown, a facet is missing, or a facet has
too few or too many values.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY = json.loads((ROOT / "taxonomy.json").read_text())["facets"]
TEXT_FIELDS = {"what_happens": (6, 45), "period": (1, 14)}  # word-count ranges


def check(record):
    problems = []
    for facet, spec in TAXONOMY.items():
        if facet not in record:
            problems.append(f"missing {facet}")
            continue
        value = record[facet]
        values = value if isinstance(value, list) else [value]
        if spec["max"] == 1 and isinstance(value, list):
            problems.append(f"{facet} must be a single value, not a list")
        if spec["max"] > 1 and not isinstance(value, list):
            problems.append(f"{facet} must be a list")
        if not spec["min"] <= len(values) <= spec["max"]:
            problems.append(f"{facet} needs {spec['min']}-{spec['max']} values, has {len(values)}")
        for v in values:
            if v not in spec["values"]:
                problems.append(f"{facet}: unknown value {v!r}")
        if len(set(values)) != len(values):
            problems.append(f"{facet}: duplicate values")
    for field, (lo, hi) in TEXT_FIELDS.items():
        words = len(str(record.get(field, "")).split())
        if not lo <= words <= hi:
            problems.append(f"{field} should be {lo}-{hi} words, has {words}")
    keywords = record.get("keywords")
    if not isinstance(keywords, list) or not 2 <= len(keywords) <= 10:
        problems.append("keywords must be a list of 2-10 terms")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tags", type=Path, help="validate a JSON list of tag records instead of the catalog")
    args = ap.parse_args()

    if args.tags:
        records = json.loads(args.tags.read_text())
    else:
        sys.path.insert(0, str(Path(__file__).parent))
        from resolve import load_catalog
        records = load_catalog()

    bad = 0
    for r in records:
        problems = check(r)
        if problems:
            bad += 1
            print(f"{r.get('id', '?')}:")
            for p in problems:
                print(f"  - {p}")
    print(f"{len(records) - bad}/{len(records)} records valid")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
