#!/usr/bin/env python3
"""MCP server for Set-Piece Vault: lets an AI agent search scenes and fetch clips as tools.

Run by an MCP client over stdio, for example:

    claude mcp add set-piece-vault -- python3 /path/to/scene-library/mcp_server.py

Needs `pip install mcp`. Optional: `pip install fastembed numpy` enables semantic search once
data/embeddings.npz exists (see tools/embed.py). Set SPV_CLIPS to use a clips folder elsewhere.
"""
import json
import os
import sys
from pathlib import Path
from typing import Annotated, Literal, Optional

from mcp.server.fastmcp import FastMCP, Image
from pydantic import Field

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))
from query import MEASURED, load_analysis, load_scenes, measured_select, select  # noqa: E402

TAXONOMY = json.loads((ROOT / "taxonomy.json").read_text())["facets"]
SCENES = load_scenes()
BY_ID = {s["id"]: s for s in SCENES}
CLIPS = Path(os.environ.get("SPV_CLIPS", ROOT / "clips")).expanduser()
ANALYSIS = ROOT / "data" / "analysis.json"

mcp = FastMCP(
    "set-piece-vault",
    instructions=(
        "Reference library of great action set-pieces from film and TV, each a 30-second clip. "
        "Find scenes with search_scenes using the controlled tags (list_tags explains every value), "
        "then get_scene for the full record, get_clip for the video file or YouTube link, and "
        "get_contact_sheet to see frames. Distinguish scenes by their tags: a samurai duel is "
        "scene_type fight.blades with region japan and combatants samurai; a medieval army battle is "
        "battle.pre_gunpowder with era medieval, a European region and combatants knights."
    ),
)


TIER_RANK = {"canon": 0, "excellent": 1}


def _facet_param(facet):
    spec = TAXONOMY[facet]
    values = Literal[tuple(spec["values"])]
    return Annotated[Optional[list[values]], Field(
        default=None, description=f"{spec['description']} Matches any of the given values.")]


def _local_file(scene):
    path = CLIPS / scene["scene_type"] / f"{scene['id']}.mp4"
    return str(path) if path.exists() else None


def _measured_param(key):
    return Annotated[Optional[list[Literal[tuple(MEASURED[key])]]], Field(
        default=None, description=f"Measured from the downloaded clip ({key}); scenes not yet analysed are left out.")]


def _summary(scene):
    measured = load_analysis().get(scene["id"], {})
    return {
        "id": scene["id"],
        "film": scene["film"],
        "year": scene["year"],
        "scene": scene["scene"],
        "scene_type": scene["scene_type"],
        "tier": scene["tier"],
        "period": scene["period"],
        "mood": scene["mood"],
        "what_happens": scene["what_happens"],
        "downloaded": _local_file(scene) is not None,
        "youtube_url": scene["clip"]["youtube_url"],
        **({"measured": {k: measured[k] for k in ("shots", "avg_shot_seconds", "pace", "aspect_name",
                                                   "lighting_key", "motion_level") if k in measured}}
           if measured else {}),
    }


def _analysis():
    return json.loads(ANALYSIS.read_text()) if ANALYSIS.exists() else {}


@mcp.tool()
def list_tags(facet: Annotated[Optional[str], Field(
        default=None, description="A facet name for its values; omit to list all facets.")] = None) -> dict:
    """Explain the controlled vocabulary: every facet, or every value of one facet with its
    definition and how many scenes carry it."""
    if facet is None:
        return {name: {"label": spec["label"], "description": spec["description"],
                       "values_per_scene": f"{spec['min']}-{spec['max']}"} for name, spec in TAXONOMY.items()}
    if facet not in TAXONOMY:
        return {"error": f"unknown facet {facet!r}", "facets": list(TAXONOMY)}
    counts = {}
    for s in SCENES:
        for v in s[facet] if isinstance(s[facet], list) else [s[facet]]:
            counts[v] = counts.get(v, 0) + 1
    return {v: {"meaning": meaning, "scenes": counts.get(v, 0)}
            for v, meaning in TAXONOMY[facet]["values"].items()}


@mcp.tool()
def search_scenes(
    scene_type: _facet_param("scene_type") = None,
    tier: _facet_param("tier") = None,
    format: _facet_param("format") = None,
    scale: _facet_param("scale") = None,
    genre: _facet_param("genre") = None,
    era: _facet_param("era") = None,
    region: _facet_param("region") = None,
    environment: _facet_param("environment") = None,
    time_of_day: _facet_param("time_of_day") = None,
    atmosphere: _facet_param("atmosphere") = None,
    mood: _facet_param("mood") = None,
    combatants: _facet_param("combatants") = None,
    weapons: _facet_param("weapons") = None,
    vehicles: _facet_param("vehicles") = None,
    technique: _facet_param("technique") = None,
    look: _facet_param("look") = None,
    medium: _facet_param("medium") = None,
    violence: _facet_param("violence") = None,
    language: _facet_param("language") = None,
    text: Annotated[Optional[str], Field(
        default=None, description="Words that must all appear somewhere in the record (film, scene, "
                                  "period, keywords, crew, notes).")] = None,
    pace: _measured_param("pace") = None,
    lighting_key: _measured_param("lighting_key") = None,
    motion_level: _measured_param("motion_level") = None,
    aspect_name: _measured_param("aspect_name") = None,
    colour: _measured_param("colour") = None,
    temperature: _measured_param("temperature") = None,
    min_avg_shot_seconds: Annotated[Optional[float], Field(
        default=None, description="Measured average shot length at least this (needs analysed clips).")] = None,
    max_avg_shot_seconds: Annotated[Optional[float], Field(
        default=None, description="Measured average shot length at most this, e.g. 2 for fast cutting.")] = None,
    downloaded_only: Annotated[bool, Field(description="Only scenes whose clip is on disk.")] = False,
    limit: Annotated[int, Field(ge=1, le=200, description="Maximum results.")] = 20,
) -> dict:
    """Find scenes by tag. Values within one facet are OR; different facets are AND.
    Results list canon scenes first. Pass tier=["canon"] for only the essential references.
    Returns short summaries; call get_scene for the full record."""
    given = locals()
    filters = [(f, set(given[f]), False) for f in TAXONOMY if given.get(f)]
    found = select(SCENES, filters, text=text)
    found = measured_select(found, load_analysis(), {k: given.get(k) for k in MEASURED},
                            min_avg_shot_seconds, max_avg_shot_seconds)
    if downloaded_only:
        found = [s for s in found if _local_file(s)]
    found = sorted(found, key=lambda s: TIER_RANK[s["tier"]])  # canon first, order otherwise kept
    return {"total": len(found), "scenes": [_summary(s) for s in found[:limit]]}


@mcp.tool()
def get_scene(scene_id: str) -> dict:
    """The full record for one scene: every tag, what happens, what to study, crew, awards, clip
    source, and measured shot data when the clip has been analysed."""
    scene = BY_ID.get(scene_id)
    if not scene:
        return {"error": f"no scene {scene_id!r}"}
    record = dict(scene)
    record["clip"] = dict(scene["clip"], local_file=_local_file(scene))
    record["clip"].pop("replay_heat", None)
    measured = _analysis().get(scene_id)
    if measured:
        record["measured"] = measured
    return record


@mcp.tool()
def get_clip(scene_id: str) -> dict:
    """Where to watch a scene: the local MP4 path when downloaded, and the YouTube link that starts
    at the 30-second window."""
    scene = BY_ID.get(scene_id)
    if not scene:
        return {"error": f"no scene {scene_id!r}"}
    c = scene["clip"]
    return {"local_file": _local_file(scene), "youtube_url": c["youtube_url"], "start": c["start"],
            "end": c["end"], "window": c["window"],
            "alternates": [f"https://www.youtube.com/watch?v={a['youtube_id']}&t={a['start']}s" for a in c["alternates"]]}


@mcp.tool()
def get_contact_sheet(scene_id: str) -> Image:
    """A grid of frames from the clip, so you can see the scene. Uses the contact sheet made by
    tools/analyze_clips.py, or the YouTube thumbnail when the clip has not been analysed."""
    scene = BY_ID.get(scene_id)
    if not scene:
        raise ValueError(f"no scene {scene_id!r}")
    sheet = CLIPS / scene["scene_type"] / f"{scene_id}.sheet.jpg"
    if sheet.exists():
        return Image(path=str(sheet))
    import urllib.request
    url = f"https://i.ytimg.com/vi/{scene['clip']['youtube_id']}/hqdefault.jpg"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return Image(data=r.read(), format="jpeg")
    except OSError as e:  # offline or removed upload
        raise ValueError(f"no contact sheet on disk and the YouTube thumbnail is unavailable: {e}")


# Weights for tag-overlap similarity: what most changes how a scene looks and plays.
WEIGHTS = {"scene_type": 3, "combatants": 2, "region": 1.5, "era": 1.5, "environment": 1.5, "weapons": 1.5,
           "vehicles": 1, "mood": 1, "atmosphere": 1, "format": 1, "genre": 1, "time_of_day": 0.5,
           "scale": 0.5, "technique": 0.5, "look": 0.5}


def _tag_similarity(a, b):
    score = 0.0
    for facet, w in WEIGHTS.items():
        x = set(a[facet] if isinstance(a[facet], list) else [a[facet]])
        y = set(b[facet] if isinstance(b[facet], list) else [b[facet]])
        if x or y:
            score += w * len(x & y) / len(x | y)
    return score / sum(WEIGHTS.values())


@mcp.tool()
def find_similar(
    scene_id: Annotated[Optional[str], Field(default=None, description="Find scenes like this one.")] = None,
    description: Annotated[Optional[str], Field(
        default=None, description="Or describe what you want in plain words (needs semantic search enabled).")] = None,
    limit: Annotated[int, Field(ge=1, le=50)] = 10,
) -> dict:
    """Scenes that look and play alike. With scene_id: by visual embeddings when available,
    otherwise by tag overlap. With description: semantic search over frames and descriptions."""
    from semantic import Semantic  # local module; optional dependencies loaded lazily
    sem = Semantic.load(ROOT)
    if description:
        if not sem:
            return {"error": "semantic search is not set up: pip install fastembed numpy, then run tools/embed.py"}
        return {"method": "semantic", "scenes": [dict(_summary(BY_ID[i]), score=round(s, 3))
                                                 for i, s in sem.search_text(description, limit)]}
    base = BY_ID.get(scene_id or "")
    if not base:
        return {"error": "give a valid scene_id or a description"}
    if sem:
        ranked = sem.similar_to(scene_id, limit)
        method = "embeddings"
    else:
        ranked = sorted(((s["id"], _tag_similarity(base, s)) for s in SCENES if s["id"] != scene_id),
                        key=lambda t: -t[1])[:limit]
        method = "tags"
    return {"method": method, "scenes": [dict(_summary(BY_ID[i]), score=round(s, 3)) for i, s in ranked]}


if __name__ == "__main__":
    mcp.run()
