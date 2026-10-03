#!/usr/bin/env python3
"""Find a YouTube clip for every scene in catalog/*.json and pick its best 30-second window.

For each scene: search YouTube, drop trailers/reactions/fan edits, score the rest on title match,
channel and views, keep the first that plays in an embedded player, then read YouTube's
"most replayed" heatmap and choose the 30 s window with the most replays. Clips without a heatmap
get an estimated window (about a third of the way in) and are marked as such.

Results are cached in data/resolved.json, so re-runs only resolve new or changed scenes.
Pin a clip by adding "video": "<id>" (and optionally "start": <seconds>) to a catalog entry. For a
long upload such as a full film, "range": [from, to] limits the window search to that stretch.

    python3 tools/resolve.py              # resolve new scenes
    python3 tools/resolve.py --refresh    # resolve everything again
    python3 tools/resolve.py --only heat-1995-bank-shootout
"""
import argparse
import json
import math
import random
import re
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import youtube  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"
RESOLVED = ROOT / "data" / "resolved.json"
CLIP = 30

STOP = {"the", "a", "an", "of", "and", "in", "on", "at", "to", "for", "part", "chapter", "episode",
        "vs", "with", "from", "by", "movie", "film", "scene", "clip", "hd", "4k", "fight", "season"}
REJECT = re.compile(
    r"\b(trailers?|teasers?|tv spot|reacts?|reactions?|reacting|best moments|moments that|dub|progression|storyboards?|animatic|bande-annonce|relives|action replay|breaking down|in \d+ minutes|on training|review|explained|explains|breakdown|"
    r"analysis|analy[sz]ing|behind the scenes|making of|bts|how they|recreat\w*|remake|parody|lego|"
    r"minecraft|gta|fortnite|roblox|gameplay|video game|walkthrough|amv|#shorts|shorts|compilation|"
    r"top \d+|ranking|ranked|supercut|cosplay|fan ?film|fan ?made|fanmade|ai generated|concept|"
    r"soundtrack|ost|music video|lyrics|full movie|interview|podcast|comparison|side by side|"
    r"pitch meeting|honest|corridor crew|stuntmen|artists react|filmmaker reacts|1 hour|10 hours|"
    r"extended mix|piano|cover|remix|nightcore|edit audio|tribute|review|essay|deleted scene|"
    r"blooper|alternate ending|audiobook|commentary|dubbed in|asmr|unboxing|toy|diorama|"
    r"reakcja|recenzja|zwiastun|analiza|fakty i mity|reaccion|reacao|tráiler|trailer oficial|"
    r"real footage|real life|documentary|veterans?|history channel|custom roars?|re-?score|"
    r"rescored|fan edit|what if|in real life|vs real|irl|breaks? down|compared|the real|real story|"
    r"real duels?|how .{0,40}(filmed|made|shot)|but with|background music|highlights|theme suite|"
    r"[a-z]+ expert|experts?|stunt ?double|vfx artist|dub(bed)? (vs|comparison)|español|latino|"
    r"castellano|türkçe|kulüp|sahnesi|legendado|dublado|doblaje|saints row|location|locations|real match|"
    r"vostfr|music video|shura no hana|theme song|opening theme|ending theme|game footage|recap|"
    r"true story|history of|real combat|combat footage|helmet cam|bodycam|spoof|mv|showreel|show reel|"
    r"vfx reel|song from|healthbars?|health bars?|re:anime|reanimated|fan animation|inside the animation|"
    r"inside the final|featurette|dubbed|voiceover|voice over|cut-?scenes?|ultimate ninja|gameplay)\b",
    re.I)
# Channels that post clean, full-quality scene clips (studio channels and established clip libraries).
GOOD_CHANNELS = {
    "movieclips": 2.5, "flashback fm": 2.0, "4kplayback": 1.5, "tnt": 1.2, "amc": 1.2,
    "warner bros. pictures": 2.0, "warner bros.": 2.0, "warner bros. entertainment": 2.0,
    "universal pictures": 2.0, "universal pictures all-access": 2.0, "sony pictures entertainment": 2.0,
    "sony pictures home entertainment": 2.0, "paramount pictures": 2.0, "paramount movies": 2.0,
    "20th century studios": 2.0, "lionsgate movies": 2.0, "lionsgate": 2.0, "netflix": 2.0,
    "hbo": 2.0, "max": 1.5, "prime video": 2.0, "marvel entertainment": 2.0, "star wars": 2.0,
    "disney": 1.5, "a24": 2.0, "focus features": 2.0, "searchlight pictures": 2.0, "mgm": 1.5,
    "crunchyroll": 2.0, "netflix anime": 2.0, "toho": 2.0, "toho movie channel": 2.0,
    "well go usa": 2.0, "shout! factory": 1.5, "the criterion collection": 2.0, "janus films": 2.0,
    "legendary": 1.5, "imax": 1.5, "fandango at home": 1.5, "screen rant plus": 0.5,
    "scenes channel": 1.0, "boxoffice movie scenes": 1.0, "best movie scenes": 0.5,
    "clipzone: high octane hits": 1.0, "clipzone: heroes & villains": 1.0,
    "clipzone: comedic callbacks": 0.5, "pixar": 1.5, "dreamworks animation": 1.5,
    "sony pictures animation": 1.5, "aniplex usa": 2.0, "toei animation": 2.0, "funimation": 1.5,
    "studio ghibli": 1.5, "gkids films": 2.0, "shudder": 1.5, "apple tv": 2.0, "bbc": 1.5,
}


def fold(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def tokens(s):
    return [t for t in fold(s).split() if t not in STOP]


def slug(s, limit=48):
    out = fold(s).replace(" ", "-")
    return out[:limit].rstrip("-")


def scene_id(scene):
    return f"{slug(scene['film'], 32)}-{scene['year']}-{slug(scene['scene'], 40)}"


# Channels that post real combat footage, documentaries, recaps or animated history, not film scenes.
BAD_CHANNELS = {"ap archive", "british pathé", "vgs - video game sophistication", "insider", "godzilla reacts", "funker530 - veteran community & combat footage", "funker530", "yarnhub", "war&history", "bocah spoiler",
                "simple history", "kings and generals", "epic history tv", "the great war", "mark felton productions"}


def score(cand, scene):
    title = fold(cand["title"])
    title_tokens = set(title.split())
    # "Warsaw 44 (Miasto 44)": the English and original titles each count as the film's name.
    names = [n for n in re.split(r"[()]", scene["film"]) if fold(n)]
    film_cov, film = 0.0, []
    for name in names:
        name_tokens = tokens(name) or fold(name).split()
        cov = sum(t in title_tokens for t in name_tokens) / len(name_tokens)
        # Sequel numbers must match exactly ("John Wick 4" is not "John Wick 2").
        if any(t not in title_tokens for t in name_tokens if t.isdigit() and len(t) < 4):
            cov = min(cov, 0.4)
        film += name_tokens
        film_cov = max(film_cov, cov)
    extra = [t for t in tokens(scene["scene"] + " " + scene["query"]) if t not in film]
    scene_cov = sum(t in title_tokens for t in set(extra)) / max(1, len(set(extra)))
    if film_cov < 0.6 and not (film_cov >= 0.34 and scene_cov >= 0.5):
        return None
    if REJECT.search(cand["title"]) or cand["channel"].lower() in BAD_CHANNELS:
        return None
    # A title naming another release year is another film ("Sicario: Day of the Soldado (2018)").
    years = {int(y) for y in re.findall(r"\b(19[0-9]{2}|20[0-3][0-9])\b", title)}
    if years and all(abs(y - int(scene["year"])) > 1 for y in years):
        return None
    d = cand["duration"]
    if d < CLIP + 8 or d > 1500:
        return None
    s = 4 * film_cov + 5 * scene_cov
    s += GOOD_CHANNELS.get(cand["channel"].lower(), 0)
    s += 0.55 * math.log10(cand["views"] + 10)
    s += 0.8 if 60 <= d <= 600 else 0
    s += 0.4 if str(scene["year"]) in title else 0
    return s


def best_window(heat, duration, lo=0, hi=None):
    """Start second of the 30 s window with the most replays (within lo..hi), with a 2 s lead-in."""
    seconds = int(duration)
    per_sec = [0.0] * (seconds + 1)
    for start, length, value in heat:
        for t in range(int(start), min(seconds, int(start + length) + 1)):
            per_sec[t] = max(per_sec[t], value)
    # The opening seconds are inflated by everyone pressing play; don't let them win.
    skip = max(3, int(duration * 0.04))
    for t in range(min(skip, seconds)):
        per_sec[t] *= 0.35
    hi = min(seconds, hi or seconds)
    best, best_sum = lo, -1.0
    running = sum(per_sec[lo:lo + CLIP])
    for start in range(lo, max(lo + 1, hi - CLIP + 1)):
        if start > lo:
            running += per_sec[start + CLIP - 1] - per_sec[start - 1]
        if running > best_sum:
            best, best_sum = start, running
    return max(lo, min(best - 2, seconds - CLIP))


def heat_string(heat, duration, samples=48):
    """Downsample the heatmap to a compact string of digits 0-9 for the timeline sparkline."""
    out = []
    for i in range(samples):
        t = (i + 0.5) * duration / samples
        v = max((value for start, length, value in heat if start <= t < start + length), default=0)
        out.append(str(min(9, round(v * 9))))
    return "".join(out)


def estimated_window(duration):
    if duration <= 75:
        return max(0, min(5, int(duration) - CLIP))
    return max(0, min(int(duration * 0.33), int(duration) - CLIP))


def lookup(video_id):
    """Title, channel and duration for a hand-picked video id."""
    info = youtube.embed_info(video_id)
    title, channel = info["title"], ""
    try:  # oEmbed has clean title and channel names
        r = youtube._request("GET", "https://www.youtube.com/oembed",
                             params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"})
        if r.ok:
            title, channel = r.json().get("title", title), r.json().get("author_name", "")
    except Exception:
        pass
    return {"id": video_id, "title": title, "channel": channel, "duration": info["duration"],
            "views": 0, "score": 99, "ok": info["ok"]}


def resolve(scene):
    pinned = scene.get("video")
    candidates = []
    if pinned:
        candidates = [lookup(pinned)]
    else:
        seen = set()
        for q in (scene["query"], f"{scene['film']} {scene['year']} {scene['scene']} scene"):
            for c in youtube.search(q):
                if c["id"] in seen:
                    continue
                seen.add(c["id"])
                s = score(c, scene)
                if s is not None:
                    candidates.append({**c, "score": round(s, 2)})
            if len(candidates) >= 3:
                break
            time.sleep(0.4)
        candidates.sort(key=lambda c: -c["score"])

    chosen, alts = None, []
    for c in candidates[:6]:
        if len(alts) >= 2:
            break
        ok = c["ok"] if "ok" in c else youtube.embeddable(c["id"])
        if not ok:
            continue
        if chosen is None:
            chosen = c
        else:
            alts.append({"id": c["id"], "title": c["title"], "channel": c["channel"],
                         "start": estimated_window(c["duration"])})
    # Kept so a wrong pick can be swapped by hand ("video": "<id>" in the catalog) without searching again.
    shortlist = [{k: c[k] for k in ("id", "title", "channel", "duration", "views", "score")}
                 for c in candidates[:8]]
    if chosen is None:
        return {"query": scene["query"], "status": "not-found", "candidates": shortlist}

    heat = youtube.heatmap(chosen["id"])
    duration = chosen["duration"] or (heat[-1][0] + heat[-1][1] if heat else 0)
    lo, hi = scene.get("range", [0, None])  # limit the window to part of a long upload
    if "start" in scene:
        start, pick = int(scene["start"]), "pinned"
    elif heat:
        start, pick = best_window(heat, duration, lo, hi), "most-replayed"
    elif hi:
        start, pick = lo + estimated_window(hi - lo), "estimated"
    else:
        start, pick = estimated_window(duration), "estimated"
    return {
        "query": scene["query"], "status": "ok", "video": chosen["id"], "title": chosen["title"],
        "channel": chosen["channel"], "duration": int(duration), "views": chosen["views"],
        "start": start, "end": min(int(duration), start + CLIP), "pick": pick, "alts": alts,
        "heat": heat_string(heat, duration) if heat else "", "candidates": shortlist,
        **({"range": scene["range"]} if "range" in scene else {}),
    }


def load_catalog():
    scenes = []
    for path in sorted(CATALOG.glob("*.json")):
        for scene in json.loads(path.read_text()):
            scene["id"] = scene_id(scene)
            scenes.append(scene)
    ids = [s["id"] for s in scenes]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        sys.exit(f"duplicate scene ids: {sorted(dupes)}")
    return scenes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="resolve every scene again")
    ap.add_argument("--retry-missing", action="store_true", help="retry scenes that found no clip")
    ap.add_argument("--only", nargs="*", default=[], help="scene ids to resolve")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    scenes = load_catalog()
    cache = json.loads(RESOLVED.read_text()) if RESOLVED.exists() else {}
    lock = threading.Lock()

    def needs(scene):
        if args.only:
            return scene["id"] in args.only
        hit = cache.get(scene["id"])
        if args.refresh or not hit or hit.get("query") != scene["query"]:
            return True
        if scene.get("video") and hit.get("video") != scene["video"]:
            return True
        if "start" in scene and hit.get("start") != scene["start"]:
            return True
        if hit.get("range") != scene.get("range"):
            return True
        if not scene.get("video") and hit.get("status") == "ok" and score(
                {"title": hit["title"], "channel": hit["channel"], "duration": hit["duration"],
                 "views": hit.get("views", 0)}, scene) is None:
            return True  # the cached pick fails the current filters
        return args.retry_missing and hit.get("status") != "ok"

    todo = [s for s in scenes if needs(s)]
    print(f"{len(scenes)} scenes in catalog, resolving {len(todo)}", flush=True)

    def work(scene):
        time.sleep(random.uniform(0.2, 1.0))
        try:
            result = resolve(scene)
        except Exception as e:  # keep going; the scene is retried on the next run
            print(f"  ! {scene['id']}: {e}", flush=True)
            return
        with lock:
            cache[scene["id"]] = result
            RESOLVED.write_text(json.dumps(cache, indent=1, ensure_ascii=False, sort_keys=True))
        mark = {"most-replayed": "*", "estimated": "~", "pinned": "!"}.get(result.get("pick"), "x")
        print(f"  {mark} {scene['id']}: {result.get('title') or result['status']}", flush=True)

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(work, todo))

    live = {s["id"] for s in scenes}
    for stale in set(cache) - live:
        del cache[stale]
    RESOLVED.write_text(json.dumps(cache, indent=1, ensure_ascii=False, sort_keys=True))
    ok = sum(1 for s in scenes if cache.get(s["id"], {}).get("status") == "ok")
    peak = sum(1 for s in scenes if cache.get(s["id"], {}).get("pick") == "most-replayed")
    print(f"done: {ok}/{len(scenes)} scenes have a clip, {peak} windows from most-replayed data")


if __name__ == "__main__":
    main()
