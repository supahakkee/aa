# Set-Piece Vault

A reference library of great action set-pieces from film and TV, built for filmmakers and for the
AI agents that help them. Every scene is a **30-second clip** with notes on what happens and what
to study, its crew and awards, and **18 tag facets** from a controlled vocabulary: scene type,
action format, scale, genre, story era and exact period, region, environment, time of day,
atmosphere, mood, who is fighting, weapons, vehicles, filmmaking technique, look, release format,
violence level and language.

The tags keep similar-looking scenes apart: a samurai duel in the rain (`fight.blades`, `japan`,
`samurai`, `katana`, `rain`) never mixes with a medieval army clash (`battle.pre_gunpowder`,
`british_isles`, `knights`, `european_sword`).

<!-- counts -->
**1093 scenes** from 748 films and series, 1923-2025, made in 35 countries; 9 h 6 min of clips.

| Family | Scenes | Scene types |
|---|---|---|
| Fight | 446 | `fight.gunfight` 125 · `fight.hand_to_hand` 113 · `fight.blades` 102 · `fight.superpowered` 47 · `fight.ring_sport` 32 · `fight.creature` 27 |
| Battle | 299 | `battle.modern_ground` 89 · `battle.pre_gunpowder` 58 · `battle.giants` 38 · `battle.air` 32 · `battle.black_powder` 30 · `battle.space` 28 · `battle.naval` 24 |
| Chase & race | 146 | `chase.vehicle` 82 · `chase.foot` 37 · `race` 21 · `chase.air` 6 |
| Stunts & spectacle | 202 | `disaster` 56 · `stunt.set_piece` 52 · `creature.attack` 43 · `vfx.showcase` 26 · `space.travel` 25 |
<!-- /counts -->

## Get it running

| You want to… | Read |
|---|---|
| Download every clip, measure it, index it and connect your agent | [`LOCAL_SETUP.md`](LOCAL_SETUP.md): one command, `python3 setup_local.py` |
| Have an agent use the library | [`AGENTS.md`](AGENTS.md): files, record format, facets, MCP tools, queries |
| See every tag and what it means | [`taxonomy.json`](taxonomy.json) |
| Add or fix scenes | [`catalog/SPEC.md`](catalog/SPEC.md) |

## Browse

```bash
./serve.sh            # http://localhost:8000
```

A filter rail on the left covers every facet, with counts that update as you filter; active
filters show as removable chips. Click any tag in a scene's details to see every scene tagged the
same way. The viewer loops the 30-second window (`−5s`/`+5s` slide it, `←`/`→` step through
results, `R` replays, `S` stars), **Play reel** runs the current results back to back, and the
**Pull list** keeps your starred scenes. Downloaded clips play from disk; the rest stream from
YouTube.

## What's in the folder

| Path | What it is |
|---|---|
| `catalog/*.json` | The source of truth: scenes, their tags and notes. |
| `taxonomy.json` | The controlled vocabulary with a definition for every value. |
| `data/scenes.json`, `data/scenes.jsonl` | Built records, one per scene (what agents read). |
| `data/resolved.json` | Which YouTube upload and 30-second window each scene uses. |
| `data/embeddings.npz` | CLIP vectors for "find similar" and plain-language search. |
| `index.html`, `data/scenes.js` | The browser. |
| `mcp_server.py` | MCP server: `list_tags`, `search_scenes`, `get_scene`, `get_clip`, `get_contact_sheet`, `find_similar`. |
| `setup_local.py` | Installs, downloads, analyses, indexes, connects the MCP server and verifies. |
| `tools/download_clips.py` | Saves the windows as MP4s in `clips/<scene_type>/` with metadata sidecars. |
| `tools/analyze_clips.py` | Shots and pace, true aspect ratio, light, colour, motion, contact sheets; `--repick` improves estimated windows. |
| `tools/embed.py` | Builds the CLIP index from clip frames (or thumbnails before download). |
| `tools/query.py` | Command-line search by facet and measured data. |
| `tools/resolve.py` | Finds a YouTube upload for each scene and picks the window from the "most replayed" graph. |
| `tools/validate.py` | Checks every tag against the taxonomy. |
| `tools/build.py` | Builds `data/`; `--standalone` writes a self-contained page. |

## Add or fix scenes

1. Add entries to a file in `catalog/` following [`catalog/SPEC.md`](catalog/SPEC.md), tags included.
2. `python3 tools/resolve.py` finds the clips (it skips trailers, reactions, fan edits, re-scores
   and uploads that refuse embedding) and picks the windows.
3. `python3 tools/validate.py` checks the tags; `python3 tools/build.py` rebuilds `data/`.
4. `python3 tools/embed.py` refreshes the search index.

If a clip shows the wrong scene, set `"video": "<YouTube id>"` on the entry (the resolver's
runners-up are under `candidates` in `data/resolved.json`), `"start": <seconds>` to fix the window,
or `"range": [from, to]` to search only part of a long upload. Every pick in the library was
checked against its upload title and corrected where it showed the wrong scene.

## Notes

- The 30-second windows come from YouTube's "most replayed" graph where it exists (filled dot ●),
  otherwise about a third of the way in (○). `setup_local.py --repick` replaces those estimates
  with the busiest 30 seconds by motion and cutting.
- Awards are wins for the film or episode, checked conservatively. Crew lists name the people most
  relevant to the scene.
- The clips are for internal reference and study. The footage belongs to its rights holders.
