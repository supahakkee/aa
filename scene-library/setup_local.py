#!/usr/bin/env python3
"""One command to set up Set-Piece Vault on this computer.

    python3 setup_local.py --sample 5        # trial run: 5 clips end to end (about 2 minutes)
    python3 setup_local.py                   # everything: all clips, analysis, search index, MCP
    python3 setup_local.py --check           # only check what is installed

Steps (each prints what it does and stops with a clear message if something is missing):
  1. check   Python 3.10+, ffmpeg/ffprobe, a JavaScript runtime for yt-dlp, free disk space
  2. install a private virtual environment in .venv with requirements.txt
  3. download every scene's 30-second clip into clips/<scene_type>/   (tools/download_clips.py)
  4. analyse shots, aspect ratio, light, colour, motion; contact sheets   (tools/analyze_clips.py)
  5. index  frames for "find similar" and plain-language search          (tools/embed.py)
  6. connect the MCP server to Claude Code and Claude Desktop when found, and write
            mcp-config.json for any other MCP client
  7. verify start the MCP server, search, fetch a clip, and write setup_report.json

Useful options: --height 720 (smaller files), --cookies-from-browser chrome (if YouTube asks you to
sign in), --repick (improve estimated windows; downloads each of those uploads once at 360p),
--only facet=value ... (download a subset), --skip-download/--skip-analysis/--skip-index,
--connect none.
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
SERVER = ROOT / "mcp_server.py"
MB_PER_CLIP = {480: 3, 720: 5, 1080: 10}


def say(msg):
    print(f"\n==> {msg}", flush=True)


def fail(msg):
    print(f"\n✗ {msg}", flush=True)
    sys.exit(1)


def run(cmd, **kw):
    print("   $ " + " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], **kw)


def install_hint(tool):
    system = platform.system()
    hints = {
        "ffmpeg": {"Darwin": "brew install ffmpeg", "Linux": "sudo apt install ffmpeg   (or your distro's package)",
                   "Windows": "winget install Gyan.FFmpeg"},
        "deno": {"Darwin": "brew install deno", "Linux": "curl -fsSL https://deno.land/install.sh | sh",
                 "Windows": "winget install DenoLand.Deno"},
    }
    return hints[tool].get(system, f"install {tool}")


def check(args, scene_count):
    say("1/7 Checking prerequisites")
    ok = True
    if sys.version_info < (3, 10):
        print(f"   ✗ Python {platform.python_version()}: need 3.10 or newer")
        ok = False
    else:
        print(f"   ✓ Python {platform.python_version()}")
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool):
            print(f"   ✓ {tool}")
        else:
            print(f"   ✗ {tool} not found: {install_hint('ffmpeg')}")
            ok = False
    if shutil.which("deno"):
        print("   ✓ deno (JavaScript runtime yt-dlp uses for YouTube)")
    elif shutil.which("node"):
        print(f"   ✓ node (works; deno is yt-dlp's preferred runtime: {install_hint('deno')})")
    else:
        print(f"   ! no deno or node: YouTube downloads will mostly fail. Install deno: {install_hint('deno')}")
    need_gb = scene_count * MB_PER_CLIP.get(args.height, 10) / 1000 * 1.3 if not args.skip_download else 0.5
    free_gb = shutil.disk_usage(ROOT).free / 1e9
    mark = "✓" if free_gb > need_gb else "✗"
    print(f"   {mark} disk: {free_gb:.0f} GB free, about {need_gb:.1f} GB needed for {scene_count} clips at {args.height}p")
    if free_gb <= need_gb:
        ok = False
    if not ok:
        fail("fix the items marked ✗ and run this again")


def ensure_venv(args):
    """Re-run this script inside .venv so nothing touches the system Python."""
    if Path(sys.prefix).resolve() == VENV.resolve():
        return
    say("2/7 Installing into a private environment (.venv)")
    if not PY.exists():
        venv.create(VENV, with_pip=True)
    if not args.no_install:
        if run([PY, "-m", "pip", "install", "--upgrade", "pip"], stdout=subprocess.DEVNULL).returncode != 0:
            fail("could not upgrade pip in .venv")
        if run([PY, "-m", "pip", "install", "-r", ROOT / "requirements.txt"]).returncode != 0:
            fail("pip install failed; see the error above")
    os.execv(str(PY), [str(PY), str(Path(__file__).resolve()), *sys.argv[1:], "--no-install"])


def step(cmd, label):
    if run(cmd).returncode != 0:
        fail(f"{label} stopped with an error (see above). Fix it and run setup_local.py again; finished work is kept.")


def mcp_entry():
    return {"command": str(PY.resolve()), "args": [str(SERVER)], "env": {"SPV_CLIPS": str(ROOT / "clips")}}


def connect(mode):
    say("6/7 Connecting the MCP server")
    entry = mcp_entry()
    (ROOT / "mcp-config.json").write_text(json.dumps({"mcpServers": {"set-piece-vault": entry}}, indent=2) + "\n")
    print(f"   ✓ wrote {ROOT / 'mcp-config.json'} (paste into any MCP client's config)")
    done = []
    if mode in ("auto", "claude-code") and shutil.which("claude"):
        subprocess.run(["claude", "mcp", "remove", "--scope", "user", "set-piece-vault"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        r = run(["claude", "mcp", "add", "--scope", "user", "-e", f"SPV_CLIPS={ROOT / 'clips'}",
                 "set-piece-vault", "--", entry["command"], *entry["args"]])
        if r.returncode == 0:
            done.append("Claude Code (all projects)")
    elif mode == "claude-code":
        print("   ! the `claude` command was not found; install Claude Code or use mcp-config.json")
    desktop = {
        "Darwin": Path.home() / "Library/Application Support/Claude/claude_desktop_config.json",
        "Windows": Path(os.environ.get("APPDATA", Path.home())) / "Claude/claude_desktop_config.json",
        "Linux": Path.home() / ".config/Claude/claude_desktop_config.json",
    }.get(platform.system())
    if mode in ("auto", "claude-desktop") and desktop and desktop.parent.exists():
        config = json.loads(desktop.read_text()) if desktop.exists() and desktop.read_text().strip() else {}
        if desktop.exists():
            shutil.copy(desktop, desktop.with_suffix(".json.bak"))
        config.setdefault("mcpServers", {})["set-piece-vault"] = entry
        desktop.write_text(json.dumps(config, indent=2) + "\n")
        done.append(f"Claude Desktop ({desktop}; restart the app)")
    for d in done:
        print(f"   ✓ connected to {d}")
    if not done:
        print("   · no Claude app found to connect automatically; use mcp-config.json")


def verify():
    say("7/7 Verifying")
    code = r'''
import asyncio, json, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def main():
    p = StdioServerParameters(command=sys.executable, args=[sys.argv[1]], env={"SPV_CLIPS": sys.argv[2]})
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            res = json.loads((await s.call_tool("search_scenes", {"downloaded_only": True, "limit": 1})).content[0].text)
            clip = None
            if res["scenes"]:
                clip = json.loads((await s.call_tool("get_clip", {"scene_id": res["scenes"][0]["id"]})).content[0].text)
            sim = json.loads((await s.call_tool("find_similar", {"description": "sword duel in the snow", "limit": 3})).content[0].text)
            print(json.dumps({"tools": tools, "downloaded": res["total"], "sample_clip": clip,
                              "semantic_search": sim.get("method", sim.get("error"))}))
asyncio.run(main())
'''
    out = subprocess.run([str(PY), "-c", code, str(SERVER), str(ROOT / "clips")], capture_output=True, text=True)
    if out.returncode != 0:
        print(out.stderr[-2000:])
        fail("the MCP server did not start; see the error above")
    result = json.loads(out.stdout.strip().splitlines()[-1])
    scenes = json.loads((ROOT / "data" / "scenes.json").read_text())["count"]
    analysis = ROOT / "data" / "analysis.json"
    report = {
        "scenes": scenes,
        "clips_on_disk": result["downloaded"],
        "clips_analysed": len(json.loads(analysis.read_text())) if analysis.exists() else 0,
        "semantic_search": result["semantic_search"],
        "mcp_tools": result["tools"],
        "sample_clip": result["sample_clip"],
        "mcp_config": str(ROOT / "mcp-config.json"),
        "failed_downloads": str(ROOT / "clips" / "report.json"),
    }
    (ROOT / "setup_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"   ✓ MCP server answers with tools: {', '.join(result['tools'])}")
    print(f"   ✓ {report['clips_on_disk']} of {scenes} clips on disk, {report['clips_analysed']} analysed")
    print(f"   ✓ plain-language search: {report['semantic_search']}")
    if result["sample_clip"] and result["sample_clip"].get("local_file"):
        print(f"   ✓ sample clip: {result['sample_clip']['local_file']}")
    print(f"\nDone. Report: {ROOT / 'setup_report.json'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only check prerequisites")
    ap.add_argument("--sample", type=int, metavar="N", help="trial run with N clips")
    ap.add_argument("--only", nargs="+", default=[], metavar="FACET=VALUE", help="download a subset (query.py filters)")
    ap.add_argument("--height", type=int, default=1080, choices=[480, 720, 1080], help="maximum clip height")
    ap.add_argument("--workers", type=int, default=3, help="parallel downloads")
    ap.add_argument("--cookies-from-browser", metavar="BROWSER", help="chrome, firefox, safari, edge…")
    ap.add_argument("--repick", action="store_true", help="improve estimated windows before analysing")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--skip-analysis", action="store_true")
    ap.add_argument("--skip-index", action="store_true")
    ap.add_argument("--connect", default="auto", choices=["auto", "claude-code", "claude-desktop", "none"])
    ap.add_argument("--no-install", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    scene_count = json.loads((ROOT / "data" / "scenes.json").read_text())["count"]
    if Path(sys.prefix).resolve() != VENV.resolve():
        check(args, args.sample or scene_count)
        if args.check:
            return
    ensure_venv(args)

    cookies = ["--cookies-from-browser", args.cookies_from_browser] if args.cookies_from_browser else []
    if not args.skip_download:
        say("3/7 Downloading clips (re-running resumes where it stopped)")
        cmd = [PY, ROOT / "tools/download_clips.py", *args.only, "--height", args.height, "--workers", args.workers, *cookies]
        if args.sample:
            cmd += ["--limit", args.sample]
        step(cmd, "Downloading")
    if not args.skip_analysis:
        say("4/7 Measuring clips and making contact sheets")
        step([PY, ROOT / "tools/analyze_clips.py", *(["--repick"] if args.repick else []), *cookies], "Analysis")
    if not args.skip_index:
        say("5/7 Building the search index")
        step([PY, ROOT / "tools/embed.py"], "Indexing")
    if args.connect != "none":
        connect(args.connect)
    verify()


if __name__ == "__main__":
    main()
