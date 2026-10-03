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


EUROPE = {"british_isles", "western_europe", "southern_europe", "northern_europe", "eastern_europe", "russia"}
SPACE = {"deep_space", "earth_orbit", "alien_world"}
OUTDOOR = {"city_street", "highway", "rooftops", "alley", "slum_shantytown", "market_bazaar", "plaza_square", "town_main_street",
           "village", "bridge", "construction_site", "skyscraper_exterior", "forest", "jungle", "bamboo_forest", "grassland",
           "hills_mountains", "cliff_canyon", "desert", "snow_ice", "beach", "river_lake", "swamp_mud", "open_sea", "sky",
           "battlefield", "trench", "ruined_city", "cemetery", "airfield"}
ERA_YEARS = {"ancient": (-9999, 499), "medieval": (500, 1499), "early_modern": (1500, 1799), "19th_century": (1800, 1899),
             "early_20th_century": (1900, 1938), "ww2": (1939, 1945), "mid_20th_century": (1946, 1979),
             "late_20th_century": (1980, 1999), "contemporary": (2000, 9999)}


def lint(r):
    """Tag combinations that are usually mistakes. Warnings, not errors: a few are deliberate."""
    w = []
    who, where, era = set(r.get("combatants", [])), r.get("region"), r.get("era")
    if who & {"samurai", "ronin", "ninja", "ashigaru_japanese_army"} and where not in ("japan", "korea", "china", "fantasy_world"):
        w.append(f"Japanese warriors but region {where}")
    if who & {"knights", "medieval_soldiers", "vikings"} and where not in EUROPE | {"fantasy_world", "middle_east", "north_africa"}:
        w.append(f"European warriors but region {where}")
    if who & {"roman_legion", "greek_hoplites", "gladiators"} and era not in ("ancient", "fantasy_world"):
        w.append(f"ancient combatants but era {era}")
    for c, e in (("ww1_soldiers", "early_20th_century"), ("ww2_soldiers", "ww2")):
        if c in who and era != e:
            w.append(f"{c} but era {era}")
    if "cowboys_gunslingers" in who and where not in ("american_frontier", "usa", "latin_america", "alien_world", "deep_space"):
        w.append(f"cowboys but region {where}")
    if r.get("scene_type") == "battle.space" and where not in SPACE | {"fantasy_world"} \
            and "outer_space" not in r.get("environment", []):
        w.append("space scene_type without a space region or outer_space environment")
    # A story set in its own present should use the era of its release year.
    if era in ERA_YEARS and isinstance(r.get("year"), int) and era in ("contemporary", "late_20th_century", "mid_20th_century"):
        lo, hi = ERA_YEARS[era]
        if r["year"] < lo:
            w.append(f"era {era} starts in {lo} but the film is from {r['year']}")
    if r.get("time_of_day") == "not_applicable" and set(r.get("environment", [])) & OUTDOOR:
        w.append("outdoor scene with time_of_day not_applicable")
    return w


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tags", type=Path, help="validate a JSON list of tag records instead of the catalog")
    ap.add_argument("--lint", action="store_true", help="also warn about unlikely tag combinations")
    args = ap.parse_args()

    if args.tags:
        records = json.loads(args.tags.read_text())
    else:
        sys.path.insert(0, str(Path(__file__).parent))
        from resolve import load_catalog
        records = load_catalog()

    if args.lint:
        warned = 0
        for r in records:
            for warning in lint(r):
                warned += 1
                print(f"warning {r.get('id', r.get('film', '?'))}: {warning}")
        print(f"{warned} warnings")

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
