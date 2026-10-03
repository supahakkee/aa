#!/usr/bin/env python3
"""Find scenes by facet. Built for agents: every filter is checked against taxonomy.json.

    python3 tools/query.py scene_type=fight.blades region=japan
    python3 tools/query.py scene_type=battle.pre_gunpowder region=british_isles,western_europe mood=epic
    python3 tools/query.py atmosphere=rain time_of_day=night --format table
    python3 tools/query.py genre=space_opera --text "trench run" --format json
    python3 tools/query.py --facets                 # list every facet and value with counts
    python3 tools/query.py --facets region          # one facet
    python3 tools/query.py scene_type=fight --max-avg-shot 2 --lighting-key low_key   # needs analysed clips

Filters: facet=value. Several values separated by commas match any of them (OR). Several filters
must all match (AND). For list facets (format, genre, environment, mood, combatants, weapons,
vehicles, technique, atmosphere) a scene matches if any of its values matches. Prefix a facet with
"not." to exclude: not.violence=graphic.

Output formats: jsonl (default, one full record per line), json, ids, paths (local clip files),
urls (YouTube links at the window start), table (human-readable).
"""
import argparse
import difflib
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY = json.loads((ROOT / "taxonomy.json").read_text())["facets"]


def load_scenes():
    return json.loads((ROOT / "data" / "scenes.json").read_text())["scenes"]


# Measured by tools/analyze_clips.py once clips are downloaded (data/analysis.json).
MEASURED = {
    "pace": ["long_take", "slow", "moderate", "fast", "rapid"],
    "lighting_key": ["low_key", "mid_key", "high_key"],
    "motion_level": ["calm", "moderate", "intense", "frenetic"],
    "aspect_name": ["4:3", "1.37:1", "1.66:1", "16:9", "1.85:1", "2:1", "2.20:1", "2.39:1", "2.76:1"],
    "colour": ["monochrome", "muted", "natural", "vivid"],
    "temperature": ["warm", "neutral", "cool"],
}


def load_analysis():
    path = ROOT / "data" / "analysis.json"
    return json.loads(path.read_text()) if path.exists() else {}


def measured_select(scenes, analysis, want=None, min_avg_shot=None, max_avg_shot=None):
    """Keep scenes whose measured clip data matches; unmeasured scenes drop out when any is asked for."""
    want = {k: set(v) for k, v in (want or {}).items() if v}
    if not want and min_avg_shot is None and max_avg_shot is None:
        return scenes
    out = []
    for s in scenes:
        m = analysis.get(s["id"])
        if not m:
            continue
        if any(m.get(k) not in vals for k, vals in want.items()):
            continue
        if min_avg_shot is not None and m["avg_shot_seconds"] < min_avg_shot:
            continue
        if max_avg_shot is not None and m["avg_shot_seconds"] > max_avg_shot:
            continue
        out.append(s)
    return out


def fold(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()


def parse_filters(items):
    filters = []
    for item in items:
        if "=" not in item:
            sys.exit(f"filter {item!r} must look like facet=value")
        facet, raw = item.split("=", 1)
        negate = facet.startswith("not.")
        facet = facet[4:] if negate else facet
        if facet not in TAXONOMY:
            hint = difflib.get_close_matches(facet, TAXONOMY, n=1)
            sys.exit(f"unknown facet {facet!r}" + (f" (did you mean {hint[0]}?)" if hint else "")
                     + f"; facets: {', '.join(TAXONOMY)}")
        values = {v.strip() for v in raw.split(",") if v.strip()}
        allowed = TAXONOMY[facet]["values"]
        for v in values:
            # "fight" matches every fight.* scene type
            if v not in allowed and not any(a.startswith(v + ".") for a in allowed):
                hint = difflib.get_close_matches(v, allowed, n=3)
                sys.exit(f"unknown {facet} value {v!r}" + (f" (did you mean {', '.join(hint)}?)" if hint else ""))
        filters.append((facet, values, negate))
    return filters


def _matches(scene, facet, values):
    have = scene.get(facet)
    have = have if isinstance(have, list) else [have]
    return any(h == v or str(h).startswith(v + ".") for h in have for v in values)


def select(scenes, filters, text=None, ids=None):
    out = []
    words = fold(text).split() if text else []
    for s in scenes:
        if ids and s["id"] not in ids:
            continue
        if any(_matches(s, f, vals) == neg for f, vals, neg in filters):
            continue
        if words:
            hay = fold(json.dumps(s, ensure_ascii=False))
            if not all(w in hay for w in words):
                continue
        out.append(s)
    return out


def show_facets(scenes, only):
    for facet, spec in TAXONOMY.items():
        if only and facet not in only:
            continue
        counts = Counter(v for s in scenes for v in (s[facet] if isinstance(s[facet], list) else [s[facet]]))
        cardinality = "one value" if spec["max"] == 1 else f"up to {spec['max']} values"
        print(f"\n{facet} — {spec['label']} ({cardinality})")
        print(f"  {spec['description']}")
        for value, meaning in spec["values"].items():
            print(f"  {counts.get(value, 0):>4}  {value:<26} {meaning}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("filters", nargs="*")
    ap.add_argument("--text", help="free-text words that must all appear in the record")
    ap.add_argument("--ids", nargs="+")
    ap.add_argument("--local", action="store_true", help="only scenes whose clip is downloaded")
    for key, values in MEASURED.items():
        ap.add_argument(f"--{key.replace('_', '-')}", nargs="+", choices=values, metavar="VALUE",
                        help=f"measured {key} (after analyze_clips.py): {', '.join(values)}")
    ap.add_argument("--min-avg-shot", type=float, metavar="SECONDS", help="measured average shot length at least")
    ap.add_argument("--max-avg-shot", type=float, metavar="SECONDS", help="measured average shot length at most")
    ap.add_argument("--format", default="jsonl", choices=["jsonl", "json", "ids", "paths", "urls", "table"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--facets", nargs="*", metavar="FACET", help="list facet values with counts and exit")
    args = ap.parse_args()

    scenes = load_scenes()
    if args.facets is not None:
        show_facets(scenes, set(args.facets))
        return
    found = select(scenes, parse_filters(args.filters), text=args.text, ids=args.ids)
    if args.local:
        found = [s for s in found if (ROOT / s["clip"]["file"]).exists()]
    analysis = load_analysis()
    found = measured_select(found, analysis, {k: getattr(args, k) for k in MEASURED},
                            args.min_avg_shot, args.max_avg_shot)
    for s in found:
        if s["id"] in analysis:
            s["measured"] = analysis[s["id"]]
    found = found[: args.limit] if args.limit else found

    if args.format == "json":
        print(json.dumps(found, indent=1, ensure_ascii=False))
    elif args.format == "jsonl":
        for s in found:
            print(json.dumps(s, ensure_ascii=False))
    elif args.format == "ids":
        print("\n".join(s["id"] for s in found))
    elif args.format == "paths":
        print("\n".join(str(ROOT / s["clip"]["file"]) for s in found))
    elif args.format == "urls":
        print("\n".join(s["clip"]["youtube_url"] for s in found))
    else:
        for s in found:
            print(f"{s['scene_type']:<22} {s['film'][:34]:<34} {s['year']}  {s['scene'][:48]:<48} "
                  f"{s['region']:<16} {s['era']}")
    print(f"{len(found)} scenes", file=sys.stderr)


if __name__ == "__main__":
    main()
