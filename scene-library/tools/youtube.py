"""Minimal YouTube client: search, embeddability check and the "most replayed" heatmap.

Uses the same public endpoints the YouTube web player calls. No API key or login needed.
"""
import json
import re
import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CONTEXT = {"client": {"clientName": "WEB", "clientVersion": "2.20250101.00.00", "hl": "en", "gl": "US"}}
API = "https://www.youtube.com/youtubei/v1/"

_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})


def _request(method, url, retries=4, **kw):
    for attempt in range(retries):
        try:
            r = _session.request(method, url, timeout=30, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            return r
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))


def _walk(obj, key):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, key)


def _text(t):
    if not t:
        return ""
    if "simpleText" in t:
        return t["simpleText"]
    return "".join(r.get("text", "") for r in t.get("runs", []))


def _seconds(clock):
    total = 0
    for part in clock.split(":") if clock else []:
        total = total * 60 + int(part)
    return total


def _views(s):
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else 0


def search(query):
    """Return video results for a query: id, title, channel, duration (s), views."""
    r = _request("POST", API + "search?prettyPrint=false", json={"context": CONTEXT, "query": query})
    out = []
    for v in _walk(r.json(), "videoRenderer"):
        if not v.get("videoId") or not v.get("lengthText"):
            continue  # live streams and premieres have no length
        out.append({
            "id": v["videoId"],
            "title": _text(v.get("title")),
            "channel": _text(v.get("ownerText")),
            "duration": _seconds(_text(v.get("lengthText"))),
            "views": _views(_text(v.get("viewCountText"))),
        })
    return out


def embed_info(video_id):
    """Check the embedded player: {"ok": plays without sign-in, "title", "duration"}."""
    r = _request("GET", f"https://www.youtube.com/embed/{video_id}",
                 headers={"Referer": "https://example.com/"})
    page = r.text.replace('\\"', '"')  # the player config is embedded as an escaped JSON string
    status = re.search(r'"previewPlayabilityStatus":\{"status":"([A-Z_]+)"', page)
    title = re.search(r'"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"', page)
    duration = re.search(r'"videoDurationSeconds":"(\d+)"', page)
    return {
        "ok": bool(status and status.group(1) == "OK" and '"playableInEmbed":true' in page),
        "title": json.loads(f'"{title.group(1)}"') if title else "",
        "duration": int(duration.group(1)) if duration else 0,
    }


def embeddable(video_id):
    """True when the video plays in an embedded player without sign-in (not age-gated)."""
    return embed_info(video_id)["ok"]


def heatmap(video_id):
    """Return [(start_seconds, duration_seconds, intensity 0..1)] or None when YouTube has none."""
    r = _request("POST", API + "next?prettyPrint=false", json={"context": CONTEXT, "videoId": video_id})
    for entity in _walk(r.json(), "macroMarkersListEntity"):
        markers = entity.get("markersList", {})
        if markers.get("markerType") == "MARKER_TYPE_HEATMAP":
            return [(int(m["startMillis"]) / 1000, int(m["durationMillis"]) / 1000,
                     float(m["intensityScoreNormalized"])) for m in markers.get("markers", [])]
    return None


if __name__ == "__main__":
    import sys
    for row in search(" ".join(sys.argv[1:]))[:10]:
        print(json.dumps(row))
