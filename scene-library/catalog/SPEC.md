# Catalog format

Each file in `catalog/` is a JSON array of scenes. One entry is one specific scene (not a whole
film). `tools/resolve.py` finds a YouTube clip for it and picks a 30-second window;
`tools/validate.py` checks the tags; `tools/build.py` writes the agent-facing records to `data/`.

```json
{
  "film": "Seven Samurai",
  "year": 1954,
  "scene": "Final battle in the rain",
  "query": "Seven Samurai final battle rain scene",
  "what_happens": "Samurai and armed farmers defend their village against mounted bandits in a torrential downpour, fighting hand to hand in the mud.",
  "why": "One or two sentences on the craft to study: blocking, choreography, camera, editing, sound, effects.",
  "director": "Akira Kurosawa",
  "country": "Japan",
  "craft": ["DP: Asakazu Nakai"],
  "accolades": ["Venice: Silver Lion"],

  "scene_type": "battle.pre_gunpowder",
  "format": ["last_stand", "massed_battle"],
  "scale": "medium",
  "genre": ["samurai_jidaigeki", "action"],
  "era": "early_modern",
  "period": "Sengoku-period Japan, 1586",
  "region": "japan",
  "environment": ["village", "swamp_mud"],
  "time_of_day": "day",
  "atmosphere": ["rain", "mud"],
  "mood": ["chaotic", "epic"],
  "combatants": ["samurai", "outlaws_bandits", "civilians"],
  "weapons": ["katana", "spear_polearm", "bow_arrow", "musket_flintlock"],
  "vehicles": ["horse"],
  "technique": ["practical_stunts", "real_location", "black_and_white"],
  "look": "live_action_bw",
  "medium": "film",
  "violence": "moderate",
  "language": "japanese",
  "keywords": ["village defense", "horse charge", "mud"]
}
```

## Field rules

- **Facets** (`scene_type` through `language`): only values from `taxonomy.json`, which defines every
  value. Single-value facets are strings; the others are lists ordered by importance, within the
  min/max counts the taxonomy gives.
- `scene_type`: `fight.*` is individuals or small groups; `battle.*` is organised forces. Classify by
  what dominates the 30-second window. A samurai duel and a medieval army clash differ in
  `scene_type`, `era`, `region`, `combatants` and `weapons`; tag all of them precisely.
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
