"""Usage: python3 -m scanner FILE [FILE ...] [--password PW] [--out DIR] [--no-engines]"""
import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import sys

from . import archive, engines, inspect, unreal
from .report import WARN, Report, human

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _progress(msg):
    print(f"… {msg}", file=sys.stderr, flush=True)


def _hashes(path):
    sha, md5 = hashlib.sha256(), hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), md5.hexdigest()


def _warnings(report):
    return sum(f.level == WARN for f in report.findings)


def scan(path, out_root, passwords, run_engines=True):
    path = os.path.abspath(path)
    name = os.path.basename(path)
    report = Report(name=name, size=os.path.getsize(path))
    report.sha256, report.md5 = _hashes(path)
    stem = re.sub(r"[^\w.-]+", "_", os.path.splitext(name)[0])[:60]
    work = os.path.join(os.path.abspath(out_root), f"{stem}-{report.sha256[:8]}")
    shutil.rmtree(work, ignore_errors=True)
    files_dir, inflated_dir = os.path.join(work, "files"), os.path.join(work, "unpacked-data")
    os.makedirs(files_dir)
    os.makedirs(inflated_dir)

    _progress(f"unpacking {name}")
    before = _warnings(report)
    if archive.archive_type(path):
        opened = archive.open_archive(path, files_dir, files_dir, name, report, passwords)
        problems = _warnings(report) - before
        report.check("Archive structure and safe unpacking", f"{opened} archive(s) opened; " + (
            f"{problems} warning(s)" if problems else "no hidden data, path tricks or links"))
    else:
        shutil.copy2(path, os.path.join(files_dir, name))
        report.check("Archive structure and safe unpacking", "not an archive; scanned as a single file")

    _progress("checking what each file really is")
    entries = sorted((inspect.Entry(files_dir, os.path.join(d, f)) for d, _, fs in os.walk(files_dir) for f in fs),
                     key=lambda e: e.rel)
    before = _warnings(report)
    for e in entries:
        label = e.label
        if label == "binary data":
            label = inspect.file_description(e.path) or label
        report.files.append((e.rel, e.size, label))
        inspect.check_name(e, report)
        inspect.check_disguise(e, report)
        if e.kind in inspect.CODE_KINDS:
            report.code_files.append(f"{e.rel} ({e.label})")
    labels = collections.Counter(e.label for e in entries)
    problems = _warnings(report) - before
    report.check("File types (by content, not name)", f"{len(entries):,} files; " + (
        f"{len(report.code_files)} program(s)/script(s)" if report.code_files else "no programs or scripts")
        + (f"; {problems} disguised or oddly named" if problems else "; nothing disguised"))
    report.section("What's inside", f"{len(entries):,} files, {human(sum(e.size for e in entries))} unpacked.\n\n"
                   + "\n".join(f"- {n} × {label}" for label, n in labels.most_common()))

    _progress("searching inside files for commands, webhooks and hidden programs")
    before = _warnings(report)
    for e in entries:
        if e.kind != "archive":
            inspect.scan_file(e, report)
    problems = _warnings(report) - before
    report.check("Hidden commands, links and programs inside files",
                 f"{problems} warning(s)" if problems else "nothing suspicious")

    rows = [r for e in entries if e.label == "Windows program (PE)" for r in [inspect.analyze_pe(e, report)] if r]
    if rows:
        report.section("Windows programs", "| File | Type | Signed | Built | Notes |\n|---|---|---|---|---|\n" +
                       "\n".join("| " + " | ".join(f"`{c}`" if i == 0 else c for i, c in enumerate(r)) + " |"
                                 for r in rows))
    for e in entries:
        if e.label == "PDF document":
            inspect.check_pdf(e, report)
    images = [e for e in entries if e.label in ("PNG image", "JPEG image")]
    if images:
        ok = sum(bool(inspect.check_image(e, report)) for e in images)
        report.check("Image files", f"{ok}/{len(images)} valid with nothing hidden after the image")

    _progress("reading Unreal packages and unpacking compressed data inside files")
    unreal.check_unreal(entries, inflated_dir, report)

    inflated = sorted(os.path.join(inflated_dir, f) for f in os.listdir(inflated_dir))
    all_files = [path] + [e.path for e in entries] + inflated

    def display(p):
        p = os.path.abspath(p)
        if p == path:
            return name
        if p.startswith(files_dir + os.sep):
            return os.path.relpath(p, files_dir)
        if p.startswith(inflated_dir + os.sep):
            return "unpacked data: " + os.path.relpath(p, inflated_dir)
        return p

    if run_engines:
        _progress("running ClamAV antivirus (loading signatures takes ~30 seconds)")
        engines.clamav([path, files_dir, inflated_dir], len(all_files), display, report)
        _progress("running YARA malware rules")
        engines.yara_scan(all_files, display, report)
    else:
        report.unchecked.append("antivirus and YARA were skipped (--no-engines)")

    with open(os.path.join(work, "report.md"), "w") as f:
        f.write(report.markdown())
    with open(os.path.join(work, "report.json"), "w") as f:
        json.dump(report.to_json(), f, indent=1)
    return report, work


def main(argv=None):
    ap = argparse.ArgumentParser(prog="scan.sh", description="Check downloaded archives for malware without running anything.")
    ap.add_argument("files", nargs="+", help="zip, 7z, rar, tar, gz, iso, or any single file")
    ap.add_argument("--password", action="append", default=[], help="archive password to try (repeatable); "
                    "'infected' is always tried")
    ap.add_argument("--out", default=os.path.join(REPO, "scan-output"), help="where reports and unpacked files go")
    ap.add_argument("--no-engines", action="store_true", help="skip ClamAV and YARA (quick structural check only)")
    args = ap.parse_args(argv)
    passwords = args.password + [p for p in archive.DEFAULT_PASSWORDS if p not in args.password]
    status = 0
    for f in args.files:
        if not os.path.isfile(f):
            print(f"{f}: not found", file=sys.stderr)
            status = 2
            continue
        report, work = scan(f, args.out, passwords, run_engines=not args.no_engines)
        print(report.markdown(include_files=False))
        print(f"Full report: {os.path.join(work, 'report.md')}\n")
    return status


if __name__ == "__main__":
    sys.exit(main())
