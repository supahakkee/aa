# zipscan

Checks downloaded archives (game mods, Unreal/Unity asset packs) for malware **without ever running
anything inside them**.

## Use

```bash
./scan.sh path/to/download.zip              # also .7z, .rar, .tar, .gz, .iso, or any single file
./scan.sh download.zip --password secret    # "infected" is always tried automatically
./scan.sh a.zip b.rar c.7z                  # several at once
python3 tests/selftest.py                   # confirms the scanner catches known tricks
```

The first run installs ClamAV, 7-Zip, unar, YARA and pefile, and downloads the ClamAV signatures and
[YARA Forge](https://github.com/YARAHQ/yara-forge) rules (about a minute). Later runs reuse them,
refreshing signatures every 12 hours and rules weekly. The YARA rules are kept in `~/.cache/zipscan`.

Each scan prints a summary and writes `scan-output/<name>-<hash>/report.md` (plus `report.json`).
The unpacked files are kept next to the report under `files/` for a closer look; `scan-output/` is
git-ignored.

To share a suspicious file, zip it with the password `infected` first so antivirus software and
GitHub leave it alone in transit.

## What it checks

1. **Archive structure**: data hidden before, between or after the files; duplicate names;
   zip-bomb ratios.
2. **Safe unpacking**: entries that try to escape the folder (`../`, absolute paths) and symbolic or
   hard links are refused. Archives inside archives are opened too, up to 3 levels deep.
3. **What each file really is**, judged by its contents rather than its name. This catches disguised
   programs (an `.exe` named `.png`), double extensions (`photo.jpg.exe`), right-to-left name tricks,
   shortcuts, scripts and Office macros.
4. **Text hidden inside files**: Discord webhooks, Telegram bots, paths to browser passwords and
   crypto wallets, Defender tampering, encoded PowerShell, download-and-run commands, startup
   persistence, and programs embedded inside data files. It also lists every web address found.
5. **Windows programs** (via pefile): architecture, signature, build date, packers
   (UPX/Themida/VMProtect…), code injection, password-decryption APIs, and auto-loading DLL names.
6. **Images**: PNG chunks and CRCs, and any data hidden after the end of the image.
7. **Unreal Engine packages**: each `.uasset`/`.umap` is read field by field to list what it
   contains and prove every byte is accounted for. It also flags Python, process-launching, URL and
   console-command use, plus Blueprint and Editor Utility scripting.
8. **Compressed data inside files**: Unreal bulk data and any zlib streams are unpacked and put
   through every check, including both engines, because text searches can't see inside them.
9. **ClamAV antivirus** on the archive, every unpacked file and every unpacked stream.
10. **YARA**: about 12,000 community malware rules on the same set.

## Verdicts

| Verdict | Meaning |
|---|---|
| CLEAN | Data files only, and every check passed. |
| NO MALWARE FOUND, BUT CONTAINS PROGRAM CODE | Nothing known-bad, but programs and scripts can't be proven safe by scanning. |
| NOT FULLY CHECKED | Part of it couldn't be opened (unknown password, unsupported format) or an engine didn't run. |
| SUSPICIOUS | At least one warning. Read the findings; some are false alarms, but each needs a look. |
| MALWARE DETECTED | ClamAV matched a signature. |

## Limits

- It's static analysis. Brand-new malware with no signature can slip past ClamAV and YARA, which is
  why programs never get a plain CLEAN.
- Unreal 5 and cooked (packaged-game) assets are only partly parsed; the report says when.
  Oodle-compressed data can't be unpacked.
- RAR support needs the `7zip-rar` package; `unar` is the fallback.

---

This repository also holds **[Set-Piece Vault](scene-library/)**, a browsable library of 377 great
action, chase, war and space scenes, each cut to a 30-second YouTube window, for filmmaking
reference. Run `scene-library/serve.sh` and open http://localhost:8000.
