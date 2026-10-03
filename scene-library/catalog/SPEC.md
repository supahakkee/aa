# Scene catalog spec

We are building a filmmaker's reference library of the best action / fight / chase / war / space / VFX
scenes ever filmed. Each entry is ONE specific scene (not a whole film). A separate pipeline will search
YouTube for each scene and cut a 30-second window, so each scene must be specific and searchable.

Write a JSON array (UTF-8, pretty-printed) of objects with exactly these keys:

```json
{
  "film": "Mad Max: Fury Road",
  "year": 2015,
  "scene": "War Rig vs. the Buzzards (Fury Road chase)",
  "category": "car-chase",
  "medium": "film",
  "country": "Australia/USA",
  "director": "George Miller",
  "craft": ["Stunt coordinator: Guy Norris", "DP: John Seale", "Editor: Margaret Sixel"],
  "accolades": ["Oscar: Best Film Editing", "Oscar: Best Production Design"],
  "techniques": ["practical stunts", "center framing", "undercranking", "vehicle stunts"],
  "why": "One or two sentences: what a filmmaker should study in THIS scene — blocking, choreography, camera, editing rhythm, VFX method, sound.",
  "query": "Mad Max Fury Road war rig buzzards chase scene"
}
```

Field rules
- `category`: exactly one key from the category list in your assignment.
- `medium`: one of `film`, `series`, `anime`, `animation`.
- `craft`: 1–4 key credits relevant to the scene (fight choreographer, stunt coordinator, DP, editor,
  VFX supervisor/house, composer). ONLY credits you are certain of. Empty list is fine.
- `accolades`: major WINS for the film/episode that you are CERTAIN of (Academy Awards, BAFTA, Emmy,
  Golden Globe, Cannes/Venice/Berlin prizes, Hong Kong Film Awards, Golden Horse, Japan Academy Prize,
  Annie, VES Awards, Taurus World Stunt Awards, Saturn, Hugo). Format `"Oscar: Best Visual Effects"`,
  `"BAFTA: Best Sound"`, `"Hong Kong Film Award: Best Action Choreography"`, `"Cannes: Palme d'Or"`.
  Wins only, no nominations. NEVER guess — an empty list is far better than a wrong award.
  Unsure of the exact category name? Leave it out.
- `techniques`: 2–6 short lowercase tags from the shared vocabulary below where possible (you may add
  others if truly needed): long take, oner, handheld, steadicam, practical stunts, practical effects,
  miniatures, cgi, motion capture, wire work, gun-fu, slow motion, bullet time, undercranking,
  shaky cam, wide-angle choreography, center framing, vehicle stunts, real aircraft, imax, crowd
  simulation, motion control, rear projection, stop motion, rotoscope, 2d animation, 3d animation,
  sound design, practical explosions, aerial photography, underwater, zero-g, single location,
  cross-cutting, montage, real location, tracking shot, pov, drone, crane, night, rain, fire, snow,
  silhouette, color grading, score-driven, improvised weapons, one vs many, duel, siege, cavalry,
  infantry, trench, beach landing, urban combat, jungle, desert.
- `why`: concrete and craft-focused, max ~45 words. No plot summaries.
- `query`: the YouTube search string most likely to surface a clip of exactly this scene
  (film title + recognisable scene name + "scene"; add year if title is ambiguous).

Selection rules
- Only genuinely great, widely acclaimed scenes — the kind that appear on "greatest scene" lists,
  are taught in film schools, or won/defined craft awards. Classics through 2025 releases.
- Prefer scenes that are famous enough that a clip of them exists on YouTube.
- Include international cinema (Hong Kong, Japan, Korea, India, Indonesia, Thailand, France, USSR/Russia,
  Poland, China, etc.) alongside Hollywood, and select TV series where they are landmark-level.
- No duplicates. Several different scenes from one film are allowed only if each is iconic.
- Accuracy over volume: if you are unsure a scene exists as described, skip it.
