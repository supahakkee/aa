# Set-Piece Vault

A browsable reference library of **377 great action set-pieces** in 18 scene types: fight
choreography, gunfights, sword duels, boxing, westerns, car and foot chases, practical stunts,
modern war, epic battles, dogfights, naval combat, space battles, space travel, VFX spectacle,
creatures, superheroes and anime. Films from 1923 to 2025 and 20+ countries, plus landmark series
(Band of Brothers, Game of Thrones, Shōgun, The Expanse, Arcane). Every scene is cut to a
**30-second window** of a YouTube upload (3 hours 8 minutes of reference in total), and each one
carries notes on what to study, its key crew, its awards and technique tags.

| Group | Scene types |
|---|---|
| Fight | Hand-to-hand & martial arts (25) · Swords & blades (20) · Gunfights (24) · Boxing (13) · Westerns (20) |
| Pursuit & Stunts | Vehicle chases (30) · Foot chases & parkour (14) · Practical stunts (25) |
| War | Modern war (31) · Epic battles (29) · Aerial combat (13) · Naval & submarine (11) |
| Space | Space battles (22) · Space travel & cosmic (23) |
| Spectacle | VFX spectacle & disaster (21) · Creatures, kaiju & mechs (18) · Superhero (18) · Anime & animation (20) |

## Browse

```bash
./serve.sh            # then open http://localhost:8000
```

The page needs to be served over HTTP (not opened as a file) for YouTube to allow the built-in
player. Opened as a file it still works, but clips open on YouTube at the window's start.

- **Bins** on the left group scenes by type: Fight, Pursuit & Stunts, War, Space and Spectacle.
- **Filters**: medium (film, series, anime, animation), era, award winners only, and technique
  chips such as *long take*, *practical stunts*, *wire work*, *imax* or *miniatures*. Chips combine.
- **Search** matches film, scene, director, crew (choreographers, DPs, editors, VFX supervisors),
  awards, country and the study notes. Press `/` to jump to it.
- **Viewer**: the 30-second window loops. `−5s` / `+5s` slide the window, `←` / `→` step through the
  current results, `R` replays, `S` adds the scene to your pull list.
- **Play reel** plays everything in the current view back to back, 30 seconds each. Filter to
  *Space Battles* + *practical effects* and press it for an instant mood reel.
- **Pull list** keeps the scenes you star (stored in your browser). *Copy pull list* gives you the
  titles with timestamped YouTube links, ready for a treatment, a shot list or `cut_clips.py`.

### How the 30 seconds are chosen

YouTube publishes a "most replayed" graph for popular videos. The resolver slides a 30-second
window along that graph and keeps the stretch viewers rewatch most, starting 2 seconds early. Those
clips show a filled dot (●) next to their timecode and the graph is drawn under the player. Clips
without the graph get an estimated window about a third of the way in (○); nudge it if it misses.

## Save clips for offline use

For editing mood reels or pre-vis, you can save the windows as MP4 files on your own machine:

```bash
pip install yt-dlp                                  # ffmpeg must be installed too
python3 tools/cut_clips.py --category gunfights     # one bin
python3 tools/cut_clips.py --list pull-list.txt     # paste "Copy pull list" into a file
python3 tools/cut_clips.py --all --height 720 --pad 3
```

Files go to `clips/<category>/<scene-id>.mp4`, which git ignores. The footage belongs to its rights
holders: keep the files for personal study and don't publish or redistribute them.

## Add or fix scenes

1. Add entries to a file in `catalog/` following [`catalog/SPEC.md`](catalog/SPEC.md).
2. `python3 tools/resolve.py` searches YouTube for the new scenes, skips trailers, reactions, fan
   edits and uploads that refuse embedding, and picks the window. Results are cached in
   `data/resolved.json`; only new or changed scenes are fetched.
3. `python3 tools/build.py` writes `data/scenes.json` and `data/scenes.js`, which the page loads.

If the resolver picks the wrong upload, set `"video": "<YouTube id>"` on the catalog entry (the
runners-up it found are listed under `candidates` in `data/resolved.json`). Add `"start": <seconds>`
to set the window by hand. Re-run steps 2 and 3.

Every pick was checked by hand against its upload title, and wrong scenes, trailers, fan edits and
re-scored versions were swapped for the right clip. Uploads still disappear from YouTube over time. `python3 tools/resolve.py --refresh` re-resolves
everything; the viewer also offers the alternate uploads it found and a YouTube search for any
clip that stops playing.

`python3 tools/build.py --standalone vault.html` writes a single self-contained page with
thumbnails embedded, for places where YouTube embeds are not allowed. Its clips open on YouTube.

## Host it

The folder is a static site. To publish it on GitHub Pages, enable Pages for the repository and
serve the `scene-library` folder (for example with a Pages workflow that uploads it as the
artifact). YouTube embeds work there because the page is served over HTTPS.

## Notes on the data

- Awards are wins for the film or episode (Oscars, BAFTAs, Emmys, Hong Kong Film Awards, Taurus
  World Stunt Awards and so on), not for the clip itself. They were checked conservatively and left
  out where uncertain, so a scene without awards listed may still have won some.
- Crew lists name the people most relevant to the scene (fight or stunt coordinator, DP, editor,
  VFX supervisor), not the full credits.
