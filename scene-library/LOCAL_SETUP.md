# Local setup: download the clips and connect the library to your agent

This is a runbook for an agent (or a person) setting up Set-Piece Vault on a computer. It ends with
every clip on disk, measured and indexed, and an MCP server your agent can call.

## Prompt to give your agent

> Set up the Set-Piece Vault scene library on this computer by following
> `scene-library/LOCAL_SETUP.md` in the repository https://github.com/supahakkee/aa (branch
> `claude/upbeat-galileo-vjoyzj`). Run the trial first, then the full setup with `--repick`.
> Report the contents of `scene-library/setup_report.json` when you finish, and tell me about any
> failed downloads listed in `scene-library/clips/report.json`. Afterwards, read
> `scene-library/AGENTS.md` so you know how to use the library's tools.

## What you need

| Requirement | Why | Install |
|---|---|---|
| Python 3.10+ | runs everything | python.org, `brew install python`, or your package manager |
| ffmpeg (with ffprobe) | cuts and measures clips | macOS `brew install ffmpeg` · Ubuntu `sudo apt install ffmpeg` · Windows `winget install Gyan.FFmpeg` |
| deno (or node) | yt-dlp needs a JavaScript runtime to read YouTube | macOS `brew install deno` · Linux `curl -fsSL https://deno.land/install.sh \| sh` · Windows `winget install DenoLand.Deno` |
| git | gets the repository | |
| A home or office internet connection | YouTube blocks downloads from cloud servers and data centres | |
| Disk space | about 10 MB per clip at 1080p, 5 MB at 720p (roughly 15 GB or 8 GB for the whole library, with frames and contact sheets) | the setup checks this |

Everything else (yt-dlp, the MCP SDK, PySceneDetect, numpy, fastembed) is installed by the setup
script into a private environment, `scene-library/.venv`, so the system Python is not touched.

## Steps

```bash
git clone https://github.com/supahakkee/aa.git
cd aa
git checkout claude/upbeat-galileo-vjoyzj
cd scene-library

python3 setup_local.py --check        # 1. prerequisites only; fix anything marked ✗
python3 setup_local.py --sample 5     # 2. trial run: 5 clips end to end (a few minutes)
python3 setup_local.py --repick       # 3. full run: every clip (resumes if interrupted)
```

What the full run does, in order (each step can be re-run; finished work is kept):

1. **check**: Python, ffmpeg, JavaScript runtime and free disk space.
2. **install**: creates `.venv` and installs `requirements.txt`.
3. **download**: saves each scene's 30-second window to `clips/<scene_type>/<id>.mp4` with a
   `<id>.json` record beside it, plus `clips/index.jsonl` and `clips/manifest.js`. Three downloads at
   a time; expect roughly 2-4 hours for the whole library (about 1,170 clips) on a typical
   connection.
4. **analyse**: measures shots, average shot length, true aspect ratio, light, colour and motion,
   and saves 12 frames and a contact sheet per clip (`<id>.frames/`, `<id>.sheet.jpg`). Results go
   into each clip's `.json` and `data/analysis.json`. About 3 seconds per clip, so about an hour
   for the whole library.
5. **index**: builds `data/embeddings.npz` from the clip frames, for "find similar" and
   plain-language search. The first run downloads the CLIP model (about 350 MB).
6. **connect**: registers the MCP server with Claude Code (`claude mcp add --scope user`) and
   Claude Desktop when they are installed, and writes `mcp-config.json` for any other client.
7. **verify**: starts the MCP server, runs a search, fetches a clip and writes `setup_report.json`.

A good result looks like this at the end:

```
==> 7/7 Verifying
   ✓ MCP server answers with tools: list_tags, search_scenes, get_scene, get_clip, get_contact_sheet, find_similar
   ✓ 1158 of 1167 clips on disk, 1158 analysed
   ✓ plain-language search: semantic
   ✓ sample clip: /…/scene-library/clips/fight.blades/….mp4
```

A few clips usually fail because an upload was removed or is blocked in your country. They are
listed in `clips/report.json`; re-running the setup retries them (it also tries alternate uploads).

### Options

| Option | Effect |
|---|---|
| `--height 720` | smaller files (about half the disk space) |
| `--only scene_type=fight.blades region=japan` | download a subset, using the same filters as `tools/query.py` |
| `--cookies-from-browser chrome` | use your browser's YouTube login when YouTube says "Sign in to confirm you're not a bot" (also firefox, safari, edge, brave) |
| `--repick` | recommended: for clips whose window was estimated (about half the library), download the upload once at 360p, find its busiest 30 seconds by motion and cutting, and re-cut the clip; adds roughly an hour |
| `--skip-download`, `--skip-analysis`, `--skip-index` | run only some steps |
| `--connect none` | don't register the MCP server anywhere |

## Connecting your agent

The setup does this automatically for Claude Code and Claude Desktop. For anything else:

- **Any MCP client** (Cursor, Windsurf, Cline, Zed, custom agents built on an MCP SDK): add the
  contents of `scene-library/mcp-config.json`. It looks like this, with your real paths:

  ```json
  {
    "mcpServers": {
      "set-piece-vault": {
        "command": "/path/to/aa/scene-library/.venv/bin/python",
        "args": ["/path/to/aa/scene-library/mcp_server.py"],
        "env": {"SPV_CLIPS": "/path/to/aa/scene-library/clips"}
      }
    }
  }
  ```

  On Windows the command is `…\scene-library\.venv\Scripts\python.exe`.
- **Claude Code by hand**: `claude mcp add --scope user set-piece-vault -- /path/to/.venv/bin/python /path/to/mcp_server.py`
- **Claude Desktop by hand**: put the `mcpServers` block above into
  `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
  `%APPDATA%\Claude\claude_desktop_config.json` (Windows) and restart the app.
- **Agents without MCP**: call the command-line tools (`tools/query.py … --format json`) or read
  `data/scenes.json`, `data/analysis.json` and `clips/index.jsonl` directly. See `AGENTS.md`.

### The MCP tools

| Tool | What it does |
|---|---|
| `list_tags(facet?)` | Explains the vocabulary: every facet, or every value of one facet with its meaning and count. |
| `search_scenes(...)` | Filters by any tag (scene_type, genre, era, region, environment, mood, combatants, weapons…), by measured data (pace, lighting_key, motion_level, aspect_name, colour, temperature, shot length), by free text, or to downloaded clips only. Values within a facet are OR; facets combine with AND. Unknown values are rejected. |
| `get_scene(scene_id)` | The full record: tags, what happens, what to study, crew, awards, clip source, measured data. |
| `get_clip(scene_id)` | The local MP4 path (when downloaded) and the YouTube link at the window start. |
| `get_contact_sheet(scene_id)` | An image of 12 frames from the clip, so a vision-capable agent can see it. |
| `find_similar(scene_id or description)` | Scenes that look and play alike, or plain-language search ("foggy forest ambush at dawn"). |

## Browsing as a person

```bash
./serve.sh     # http://localhost:8000
```

Downloaded clips play from disk (they show an "On disk" badge); the rest stream from YouTube.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Sign in to confirm you're not a bot" | Re-run with `--cookies-from-browser chrome` (or your browser) while signed in to YouTube in that browser. Lower `--workers` to 1 or 2. |
| "No supported JavaScript runtime", "HTTP Error 403" or many formats missing | Install deno, then re-run (setup upgrades yt-dlp; YouTube changes often, so `.venv/bin/pip install -U "yt-dlp[default]"` fixes most new breakage). |
| `ffmpeg` / `ffprobe` not found | Install ffmpeg (see the table above) and open a new terminal. |
| Many "Video unavailable" | The upload is region-locked or removed; the alternates are tried automatically. Report the ids in `clips/report.json` to whoever maintains the catalog. |
| `pip install` fails building a package | Use Python 3.11 or 3.12; very new Python versions sometimes lack wheels for onnxruntime or opencv. |
| MCP server not listed in Claude | Restart the app. In Claude Code run `claude mcp list`. |
| Out of disk space | Re-run with `--height 720`, or use `--only` for the parts you need. |

The clips are for internal reference and study. The footage belongs to its rights holders; don't
publish or redistribute it.
