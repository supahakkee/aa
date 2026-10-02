"""Runs the two signature engines: ClamAV (antivirus) and YARA (community malware rules)."""
import os
import re
import shutil
import subprocess

from .report import DANGER, INFO, WARN

HOME = os.environ.get("ZIPSCAN_HOME", os.path.expanduser("~/.cache/zipscan"))
YARA_SOURCE = os.path.join(HOME, "yara-forge.yar")
YARA_COMPILED = os.path.join(HOME, "yara-forge.compiled")
EXTERNALS = dict(filename="", filepath="", extension="", filetype="", owner="")


def clamav(paths, file_count, display, report):
    if not shutil.which("clamscan"):
        report.unchecked.append("ClamAV isn't installed (run ./setup.sh)")
        report.check("ClamAV antivirus", "not run")
        return
    version = subprocess.run(["clamscan", "--version"], capture_output=True, text=True).stdout.strip()
    cmd = ["clamscan", "-r", "--infected", "--no-summary", "--stdout",
           "--scan-archive=yes", "--heuristic-alerts=yes", "--alert-encrypted=yes", "--alert-macros=yes",
           "--alert-broken=yes", "--alert-exceeds-max=yes", "--max-filesize=2000M", "--max-scansize=2000M",
           "--max-recursion=30", "--max-files=200000", "--", *paths]
    res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if res.returncode not in (0, 1):
        tail = (res.stderr or res.stdout).strip().splitlines()[-1:] or ["unknown error"]
        report.unchecked.append(f"ClamAV failed to run: {tail[0]}")
        report.check("ClamAV antivirus", "failed to run")
        return
    hits = 0
    for line in res.stdout.splitlines():
        m = re.match(r"(.*): (\S+) FOUND$", line)
        if not m:
            continue
        where, sig = display(m.group(1)), m.group(2)
        if sig.startswith("Heuristics.Encrypted"):
            report.add(INFO, where, f"ClamAV: password-protected, so ClamAV couldn't look inside it directly ({sig})")
        elif sig.startswith("Heuristics.Limits"):
            report.add(INFO, where, f"ClamAV: too big to scan completely ({sig})")
        elif sig.startswith(("Heuristics.", "PUA.")):
            report.add(WARN, where, f"ClamAV heuristic matched: {sig}")
            hits += 1
        else:
            report.add(DANGER, where, f"ClamAV detected {sig}")
            hits += 1
    report.check("ClamAV antivirus", f"{hits} detection(s) across {file_count:,} files ({version})")


def yara_scan(files, display, report):
    try:
        import yara
    except ImportError:
        report.unchecked.append("YARA isn't installed (run ./setup.sh)")
        report.check("YARA malware rules", "not run")
        return
    if os.path.exists(YARA_COMPILED):
        rules = yara.load(YARA_COMPILED)
    elif os.path.exists(YARA_SOURCE):
        rules = yara.compile(filepath=YARA_SOURCE, externals=EXTERNALS)
    else:
        report.unchecked.append("YARA rules aren't downloaded (run ./setup.sh)")
        report.check("YARA malware rules", "not run")
        return
    count = sum(1 for _ in rules)
    matched = 0
    for path in files:
        name = os.path.basename(path)
        externals = dict(EXTERNALS, filename=name, filepath=path, extension=os.path.splitext(name)[1])
        try:
            matches = rules.match(path, externals=externals, timeout=180)
        except yara.TimeoutError:
            report.add(INFO, display(path), "YARA scan timed out on this file")
            continue
        except yara.Error as e:
            if os.path.getsize(path):
                report.add(INFO, display(path), f"YARA couldn't scan it ({e})")
            continue
        for m in matches:
            desc = m.meta.get("description", "")
            report.add(WARN, display(path), f"YARA rule {m.rule}" + (f": {desc}" if desc else ""))
            matched += 1
    report.check("YARA malware rules", f"{matched} match(es) across {len(files):,} files ({count:,} rules)")
