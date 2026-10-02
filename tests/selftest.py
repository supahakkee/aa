"""Builds harmless archives that use real malware tricks and checks the scanner catches each one.
Run: python3 tests/selftest.py   (ClamAV/YARA cases are skipped if ./setup.sh hasn't been run)"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scanner.__main__ import scan  # noqa: E402

# Not real programs: just enough header for the scanner to recognise a Windows executable.
FAKE_EXE = (b"MZ" + b"\x00" * 58 + struct.pack("<I", 0x80) + b"\x00" * 14
            + b"This program cannot be run in DOS mode.\r\r\n$" + b"\x00" * 7 + b"PE\x00\x00" + b"\x00" * 256)
# The standard antivirus test string, split so this source file itself doesn't trigger antivirus.
EICAR = ("X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-" + "ANTIVIRUS-TEST-FILE!$H+H*").encode()


def png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


def make_zip(path, members, trailing=b""):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    if trailing:
        with open(path, "ab") as f:
            f.write(trailing)


def messages(report):
    return [(f.level, f.where, f.message) for f in report.findings]


def expect(report, level, text, where=None):
    for lvl, w, msg in messages(report):
        if lvl == level and text in msg and (where is None or where in w):
            return
    raise AssertionError(f"{report.name}: expected a {level} finding containing {text!r}\n"
                         + "\n".join(map(str, messages(report))))


def main():
    have_engines = shutil.which("clamscan") is not None
    tmp = tempfile.mkdtemp(prefix="zipscan-test-")
    out = os.path.join(tmp, "out")
    passed = []
    try:
        clean = os.path.join(tmp, "clean.zip")
        make_zip(clean, {"textures/rock.png": png(), "readme.txt": b"Thanks for downloading!\n"})
        r, _ = scan(clean, out, ["infected"], run_engines=have_engines)
        assert r.verdict()[0] == ("CLEAN" if have_engines else "NOT FULLY CHECKED"), (r.verdict(), messages(r))
        passed.append("clean archive is CLEAN")

        tricky = os.path.join(tmp, "tricky.zip")
        make_zip(tricky, {
            "../escape.txt": b"hi",
            "holiday.jpg.exe": FAKE_EXE,
            "notes.png": FAKE_EXE,
            "readme.txt": b"see https://discord.com/api/webhooks/123/abc\n",
            "pic.png": png() + b"PK\x03\x04hidden payload",
            "install.bat": b"powershell -enc SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQA\n",
        }, trailing=b"extra bytes after the zip")
        r, work = scan(tricky, out, ["infected"], run_engines=False)
        expect(r, "warn", "outside its folder")
        expect(r, "warn", "double extension", "holiday.jpg.exe")
        expect(r, "warn", "disguised program", "notes.png")
        expect(r, "warn", "Discord webhook", "readme.txt")
        expect(r, "warn", "extra data after the end of the image", "pic.png")
        expect(r, "warn", "hidden data after the end of the zip")
        expect(r, "warn", "PowerShell running a hidden (encoded) command", "install.bat")
        assert not os.path.exists(os.path.join(work, "escape.txt")), "../ entry escaped the unpack folder"
        assert any("install.bat" in c for c in r.code_files)
        assert r.verdict()[0] == "SUSPICIOUS"
        passed.append("path escape, double extension, disguised program, webhook, image payload, "
                      "trailing zip data and encoded PowerShell all caught")

        nested = os.path.join(tmp, "nested.zip")
        inner = os.path.join(tmp, "inner.zip")
        make_zip(inner, {"deep/evil.scr": FAKE_EXE})
        make_zip(nested, {"inner.zip": open(inner, "rb").read()})
        r, _ = scan(nested, out, ["infected"], run_engines=False)
        assert any(p.endswith("evil.scr") for p, _, _ in r.files), r.files
        assert r.code_files
        passed.append("archive inside an archive is opened and scanned")

        if shutil.which("7z"):
            secret = os.path.join(tmp, "secret.txt")
            open(secret, "wb").write(b"inside a password-protected archive")
            for name, extra in (("pw.zip", []), ("pw-aes.zip", ["-mem=AES256"]), ("pw.7z", ["-mhe=on"])):
                path = os.path.join(tmp, name)
                subprocess.run(["7z", "a", "-bd", "-pinfected", *extra, path, secret], check=True, capture_output=True)
                r, _ = scan(path, out, ["infected"], run_engines=False)
                assert any(p.endswith("secret.txt") for p, _, _ in r.files), (name, messages(r), r.unchecked)
                expect(r, "info", "opened with password 'infected'")
            passed.append("password-protected zip, AES zip and encrypted 7z opened with 'infected'")

        if have_engines:
            eicar = os.path.join(tmp, "eicar.zip")
            make_zip(eicar, {"tool/eicar.com": EICAR})
            r, _ = scan(eicar, out, ["infected"], run_engines=True)
            expect(r, "danger", "ClamAV detected")
            assert r.verdict()[0] == "MALWARE DETECTED"
            passed.append("antivirus test file detected as MALWARE")
        else:
            print("skipped ClamAV/YARA cases (run ./setup.sh first)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for p in passed:
        print("ok -", p)
    print(f"{len(passed)} checks passed")


if __name__ == "__main__":
    main()
