# Catalog format

Each file in `catalog/` is a JSON array of scenes. One entry is one specific scene (not a whole
film). `tools/resolve.py` finds a YouTube clip for it and picks a 30-second window;
`tools/validate.py` checks the tags; `tools/build.py` writes the agent-facing records to `data/`.

```json
{
  "film": "13 Assassins",
  "year": 2010,
  "scene": "Ochiai village battle",
  "query": "13 Assassins village battle scene",
  "what_happens": "Thirteen samurai spring a trap on a cruel lord's 200-man escort inside a fortified village, sealing streets with barricades, blasting them with explosives and arrows, then wading in with swords.",
  "why": "One or two sentences on the craft to study: blocking, choreography, camera, editing, sound, effects.",
  "director": "Takashi Miike",
  "country": "Japan/UK",
  "craft": [],
  "accolades": [],

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
  "look": "live_action_color",
  "medium": "film",
  "violence": "graphic",
  "language": "japanese",
  "keywords": ["booby-trapped village", "flaming bulls", "barricades", "takashi miike"]
}
```

## Field rules

- **Scope**: live-action films and series released in 2000 or later. No animation or anime.
- **Facets** (`scene_type` through `language`): only values from `taxonomy.json`, which defines every
  value. Single-value facets are strings; the others are lists ordered by importance, within the
  min/max counts the taxonomy gives.
- `scene_type`: `fight.*` is individuals or small groups; `battle.*` is organised forces. Classify by
  what dominates the 30-second window. A samurai duel and a medieval army clash differ in
  `scene_type`, `era`, `region`, `combatants` and `weapons`; tag all of them precisely.
- `tier`: canon only for scenes routinely on greatest-scene lists, award-defining or widely taught;
  excellent for the best of their kind. A scene that is merely good, or that a better example of the
  same kind already covers, does not belong in the library.
- `era`, `region`, `period`: the story setting, not where or when the film was made.
- `what_happens`: 6-45 words describing what is visibly on screen, in your own words. No dialogue.
- `why`: the craft lesson, around 45 words at most.
- `period`: the exact setting in 1-14 words ("Omaha Beach, Normandy, 6 June 1944").
- `keywords`: 2-10 lowercase search terms the facets don't already cover.
- `craft` and `accolades`: only facts you are sure of. Accolades are wins for the film or episode.
- `query`: the YouTube search most likely to surface a clip of exactly this scene.

## Optional clip controls

- `"video": "<YouTube id>"` pins the upload when the resolver picks the wrong one.
- `"start": <seconds>` sets the window start by hand.
- `"range": [from, to]` limits the window search to part of a long upload (such as a full film).

Run `python3 tools/resolve.py && python3 tools/validate.py && python3 tools/build.py` after editing.
