# Set-Piece Vault: guide for agents

This folder is a reference library of action set-pieces from film and series (fights, battles,
chases, stunts, disasters, space; `count` in `data/scenes.json` gives the current total). Each scene
is a **30-second clip** described by a fixed set of **facets**, every one drawn from a controlled
vocabulary. Use the facets to find scenes; don't guess from film titles.

**Easiest way in: the MCP server.** `LOCAL_SETUP.md` sets everything up and connects it. Its tools
(`list_tags`, `search_scenes`, `get_scene`, `get_clip`, `get_contact_sheet`, `find_similar`) wrap
everything below, validate tag values for you, and return images you can look at. Without MCP, use
the files and command-line tools described here.

## Files

| Path | What it is |
|---|---|
| `taxonomy.json` | The vocabulary: every facet, its allowed values, a definition for each value, and how many values a scene carries. Read this before filtering. |
| `data/scenes.json` | All scenes: `{"version": 2, "count": N, "scenes": [ ... ]}`. |
| `data/scenes.jsonl` | The same records, one JSON object per line. |
| `clips/<scene_type>/<id>.mp4` | The 30-second clip, once downloaded with `tools/download_clips.py`. |
| `clips/<scene_type>/<id>.json` | The scene's record plus `local_file` and download details. |
| `clips/index.jsonl` | Every downloaded clip's record, one per line. |
| `clips/<scene_type>/<id>.sheet.jpg` | Contact sheet: 12 frames from the clip in a 4x3 grid (after analysis). |
| `clips/<scene_type>/<id>.frames/` | Those 12 frames as separate JPEGs. |
| `data/analysis.json` | Measured data per downloaded clip (below), keyed by scene id. |
| `data/embeddings.npz` | CLIP vectors for "find similar" and plain-language search. |
| `mcp_server.py` | The MCP server. |
| `tools/query.py` | Command-line search by facet (below). |

## A record

```json
{
  "id": "13-assassins-2010-ochiai-village-battle",
  "film": "13 Assassins", "year": 2010, "scene": "Ochiai village battle",
  "what_happens": "Literal description of what is on screen.",
  "what_to_study": "The craft lesson: choreography, camera, editing, sound, effects.",

  "scene_type": "battle.pre_gunpowder",
  "tier": "canon",
  "format": ["ambush", "massed_battle"],
  "scale": "army",
  "genre": ["samurai_jidaigeki", "action", "drama"],
  "era": "19th_century",
  "period": "Ochiai post town, Japan, 1844",
  "region": "japan",
  "environment": ["village", "town_main_street"],
  "time_of_day": "day",
  "atmosphere": ["fire", "explosions", "smoke"],
  "mood": ["chaotic", "epic", "brutal"],
  "combatants": ["samurai", "ronin"],
  "weapons": ["katana", "explosives", "bow_arrow", "spear_polearm"],
  "vehicles": [],
  "technique": ["practical_effects", "practical_explosions", "large_crowds", "fast_cutting"],
  "look": "live_action_color", "medium": "film", "violence": "graphic", "language": "japanese",
  "keywords": ["booby-trapped village", "flaming bulls", "barricades", "takashi miike"],

  "director": "Takashi Miike", "production_country": "Japan/UK",
  "crew": [], "awards": [],
  "clip": {
    "file": "clips/battle.pre_gunpowder/13-assassins-2010-ochiai-village-battle.mp4",
    "youtube_id": "…", "youtube_url": "https://www.youtube.com/watch?v=…&t=57s",
    "start": 57, "end": 87, "seconds": 30,
    "window": "most_replayed",
    "source_title": "…", "source_channel": "…", "source_views": 0, "source_duration": 0,
    "replay_heat": "0123…", "alternates": [{"youtube_id": "…", "start": 40, "title": "…", "channel": "…"}]
  }
}
```

(Values above are illustrative; read the real record from `data/scenes.json`.)

## The facets

Every value is defined in `taxonomy.json`. Lists are ordered: the first value matters most.

| Facet | Values | Answers |
|---|---|---|
| `scene_type` | exactly 1 | What kind of set-piece. `fight.*` = individuals or small groups; `battle.*` = organised forces; `chase.*`, `race`, `stunt.set_piece`, `creature.attack`, `disaster`, `vfx.showcase`, `space.travel`. |
| `tier` | 1 | How essential: canon (every filmmaker should know it) or excellent (among the best of its kind); scenes below that bar were cut. Search results list canon first; ask for `tier=canon` when you want only the essentials. |
| `format` | 1-2 | How the action is structured: duel, one_vs_many, ambush, siege, standoff, pursuit, dogfight… |
| `scale` | 1 | How many participants: solo, one_on_one, small_group, one_vs_many, medium, army, fleet, city_scale. |
| `genre` | 1-3 | Genre of the source film (first = primary). |
| `era` | 1 | When the story happens (ancient … contemporary, near/far future, fantasy_world). |
| `period` | text | The exact setting in a few words. |
| `region` | 1 | Where the story happens (japan, british_isles, american_frontier, deep_space…). |
| `environment` | 1-3 | Physical spaces (corridor, rooftops, forest, trench, open_sea, outer_space…). |
| `time_of_day` | 1 | day, golden_hour, twilight, night, mixed, not_applicable. |
| `atmosphere` | 0-3 | Weather and elements (rain, snow, fog_mist, smoke, fire, sandstorm…). Empty = clear. |
| `mood` | 1-3 | How it feels (tense, chaotic, brutal, graceful, epic, terrifying, awe…). |
| `combatants` | 1-4 | Who is in the action (samurai, knights, vikings, ww2_soldiers, police, jedi_sith, kaiju…). |
| `weapons` | 0-5 | Weapons in use (katana, european_sword, handgun, artillery_cannon, superpowers…). |
| `vehicles` | 0-3 | Vehicles and mounts (car, motorcycle, horse, warship, starfighter…). |
| `technique` | 2-6 | Craft worth studying (long_take, practical_stunts, wire_work, cgi, imax_large_format…). |
| `look` | 1 | live_action_color or live_action_bw (the library is live action only). |
| `medium` | 1 | film or series. |
| `violence` | 1 | none, mild, moderate, graphic. |
| `language` | 1 | Original spoken language. |

### Telling similar scenes apart

The facets are designed so that superficially similar scenes never collapse together:

- **Samurai sword duel**: `scene_type=fight.blades`, `region=japan`, `combatants` has `samurai` or `ronin`, `weapons` has `katana`.
- **Medieval knights in battle**: `scene_type=battle.pre_gunpowder`, `era=medieval`, `region` in Europe, `combatants` has `knights` or `medieval_soldiers`, `weapons` has `european_sword`.
- **Samurai army battle**: `scene_type=battle.pre_gunpowder` (or `battle.black_powder` when arquebuses dominate), `region=japan`, `combatants` has `ashigaru_japanese_army` or `samurai`.
- **Lightsaber duel**: `scene_type=fight.blades`, `weapons` has `lightsaber`, `era=fantasy_world`.

## Querying

```bash
python3 tools/query.py --facets                      # every facet and value with counts
python3 tools/query.py --facets region combatants    # just these
python3 tools/query.py scene_type=fight.blades region=japan --format table
python3 tools/query.py scene_type=battle.pre_gunpowder era=medieval combatants=knights,medieval_soldiers
python3 tools/query.py scene_type=chase.vehicle time_of_day=night environment=city_street,highway
python3 tools/query.py scene_type=fight technique=long_take          # "fight" matches every fight.*
python3 tools/query.py scene_type=battle.space format=dogfight --format urls
python3 tools/query.py atmosphere=rain mood=tense not.violence=graphic
python3 tools/query.py --text "hallway" --local --format paths        # downloaded clips only
```

Rules: `facet=value` filters; commas inside one filter mean OR; separate filters are AND; a
list facet matches when any of its values matches; `not.` excludes. Unknown facets or values are
rejected with a suggestion, so a typo never silently returns nothing. Output formats: `jsonl`
(default), `json`, `ids`, `paths`, `urls`, `table`. The count goes to stderr.

In Python:

```python
import json
scenes = json.load(open("data/scenes.json"))["scenes"]
rain_duels = [s for s in scenes
              if s["scene_type"] == "fight.blades" and "rain" in s["atmosphere"]]
for s in rain_duels:
    print(s["film"], s["year"], s["scene"], s["clip"]["file"], s["clip"]["youtube_url"])
```

## Measured clip data

After `tools/analyze_clips.py` runs (setup does this), every downloaded clip also has measured
facts under `measured` in its sidecar and in `data/analysis.json`:

| Field | Meaning |
|---|---|
| `shots`, `avg_shot_seconds`, `cuts_per_minute`, `cut_times` | Editing pace from shot detection. |
| `pace` | `long_take` (no cut), `slow` (>6 s per shot), `moderate` (3-6 s), `fast` (1.5-3 s), `rapid` (<1.5 s). |
| `aspect_ratio`, `aspect_name` | The picture's real shape with letterbox bars removed (`2.39:1`, `1.85:1`, `16:9`…). |
| `brightness`, `contrast`, `lighting_key` | 0-1 values; `low_key`, `mid_key`, `high_key`. |
| `saturation`, `colour` | `monochrome`, `muted`, `natural`, `vivid`. |
| `warmth`, `temperature` | `warm`, `neutral`, `cool`. |
| `palette` | Six dominant colours with their share of the frame. |
| `motion`, `motion_level`, `motion_curve` | How much changes on screen: `calm`, `moderate`, `intense`, `frenetic`; per-second curve 0-9. |

Filter on them with `tools/query.py --pace rapid --lighting-key low_key --max-avg-shot 2`, or the
matching `search_scenes` parameters.

## Plain-language and visual search

`find_similar` (MCP) and `tools/semantic.py` use CLIP: each scene has an image vector (its frames,
or YouTube thumbnails until downloaded) and a text vector (its description and tags). Use it when
no tag fits: "foggy forest ambush at dawn", "lone figure walking out of an explosion", or "scenes
that look like this one". Combine with tags for precision: search semantically, then check the
returned scenes' facets.

## Getting the clips

`clip.file` is where the MP4 lives once downloaded. Check that it exists; if not, use
`clip.youtube_url` (opens YouTube at the window start; watch until `clip.end`). To download:

```bash
python3 setup_local.py                                       # everything (see LOCAL_SETUP.md)
python3 tools/download_clips.py scene_type=fight.blades      # or only some, same filters as query.py
python3 tools/download_clips.py --cookies-from-browser chrome  # if YouTube asks to sign in
```

YouTube blocks downloads from cloud servers, so run it on a desktop or home connection.

## Notes

- `clip.window`: `most_replayed` means the 30 seconds come from YouTube's replay graph (the part
  viewers rewatch most); `motion_peak` means the busiest 30 seconds by motion and cutting
  (`setup_local.py --repick`); `estimated` means about a third of the way into the upload;
  `hand_picked` means set by hand.
- `what_happens` and `what_to_study` are original descriptions, not dialogue or script.
- `awards` are wins for the film or episode, not the clip; absence does not mean none.
- Use `violence` to choose what is safe to show a given audience.
- The footage belongs to its rights holders. Use the clips for internal reference and study.
