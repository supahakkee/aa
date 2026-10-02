"""Opens archives without trusting them: structure checks first, then an unpack that can't
write outside its own folder, then the same again for any archives found inside."""
import collections
import mmap
import os
import re
import shutil
import stat
import struct
import subprocess
import zipfile

from .report import INFO, WARN, human

MAX_TOTAL_BYTES = 8 << 30   # refuse to unpack more than this (zip bombs)
MAX_RATIO = 1000            # compression ratio no real file reaches
MAX_DEPTH = 3               # archives inside archives inside archives
DEFAULT_PASSWORDS = ["infected"]

_SIGNATURES = [
    (0, b"PK\x03\x04", "zip"), (0, b"PK\x05\x06", "zip"),
    (0, b"7z\xbc\xaf\x27\x1c", "7z"), (0, b"Rar!\x1a\x07", "rar"),
    (0, b"\x1f\x8b\x08", "gzip"), (0, b"\xfd7zXZ\x00", "xz"), (0, b"\x28\xb5\x2f\xfd", "zstd"),
    (0, b"MSCF\x00\x00\x00\x00", "cab"), (257, b"ustar", "tar"), (0x8001, b"CD001", "iso"),
]


def archive_type(path):
    try:
        with open(path, "rb") as f:
            head = f.read(0x8006)
    except OSError:
        return None
    for off, sig, kind in _SIGNATURES:
        if head[off:off + len(sig)] == sig:
            return kind
    if head[:3] == b"BZh" and len(head) > 3 and head[3] in b"123456789":
        return "bzip2"
    return None


def _unsafe(name):
    n = name.replace("\\", "/")
    if n.startswith("/") or re.match(r"[A-Za-z]:", n):
        return "uses an absolute path"
    if ".." in n.split("/"):
        return "tries to write outside its folder (../)"
    return None


def _run(cmd):
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace")


def _last_line(proc):
    lines = [l.strip() for l in (proc.stderr + proc.stdout).splitlines() if l.strip()]
    return lines[-1] if lines else f"exit code {proc.returncode}"


def check_zip(path, where, report):
    """Looks for data hidden around or between the files, which a normal zip never has."""
    if os.path.getsize(path) == 0:
        return
    with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m, \
            zipfile.ZipFile(path) as z:
        infos = sorted(z.infolist(), key=lambda i: i.header_offset)
        start = infos[0].header_offset if infos else z.start_dir
        if start:
            report.add(WARN, where, f"{start:,} bytes of unknown data before the first file "
                                    "(a self-extracting program, or something hidden)")
        eocd = m.rfind(b"PK\x05\x06")
        if eocd >= 0 and eocd + 22 <= len(m):
            comment_len = struct.unpack_from("<H", m, eocd + 20)[0]
            trailing = len(m) - (eocd + 22 + comment_len)
            if trailing > 0:
                report.add(WARN, where, f"{trailing:,} bytes of hidden data after the end of the zip")
            if comment_len:
                comment = bytes(m[eocd + 22:eocd + 22 + min(comment_len, 200)]).decode("latin-1")
                report.add(INFO, where, f"zip comment: {comment!r}")
        ends = [i.header_offset for i in infos[1:]] + [z.start_dir]
        for info, nxt in zip(infos, ends):
            o = info.header_offset
            if m[o:o + 4] != b"PK\x03\x04":
                report.add(WARN, where, f"'{info.filename}': entry header is missing (malformed zip)")
                continue
            name_len, extra_len = struct.unpack_from("<HH", m, o + 26)
            gap = nxt - (o + 30 + name_len + extra_len + info.compress_size)
            if gap == 0 or (info.flag_bits & 0x08 and gap in (12, 16, 20, 24)):
                continue  # 12-24 bytes is the standard trailer some zip tools write after each file
            if gap > 0:
                report.add(WARN, where, f"{gap:,} unexplained bytes hidden after '{info.filename}'")
            else:
                report.add(WARN, where, f"'{info.filename}' overlaps the next file (malformed zip or zip-bomb trick)")
        names = collections.Counter(i.filename.replace("\\", "/").rstrip("/") for i in infos)
        dups = sorted(n for n, c in names.items() if c > 1)
        if dups:
            report.add(WARN, where, f"the same name appears more than once ({', '.join(dups[:5])}); "
                                    "that can hide which file you actually get")


def _too_big(sizes, where, report):
    total = sum(u for u, _ in sizes)
    if total > MAX_TOTAL_BYTES:
        report.add(WARN, where, f"would unpack to {human(total)} (zip bomb?); not unpacked")
        return True
    for u, c in sizes:
        if c and u > 100 << 20 and u / c > MAX_RATIO:
            report.add(WARN, where, f"a file compresses {u // c:,}:1, which only zip bombs do; not unpacked")
            return True
    return False


def _zip_password(z, infos, passwords):
    encrypted = [i for i in infos if i.flag_bits & 1 and not i.is_dir()]
    probe = min(encrypted, key=lambda i: i.file_size)
    for pw in passwords:
        try:
            with z.open(probe, pwd=pw.encode()) as f:
                while f.read(1 << 20):
                    pass
            return pw
        except (RuntimeError, zipfile.BadZipFile):
            continue  # wrong password (a CRC mismatch also means wrong password)
    return None


def _extract_zip(path, dest, where, report, passwords):
    """Returns False when 7-Zip should take over (AES encryption, unusual compression, unknown password)."""
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if _too_big([(i.file_size, i.compress_size) for i in infos], where, report):
            return True
        pwd = None
        if any(i.flag_bits & 1 for i in infos):
            pw = _zip_password(z, infos, passwords)
            if pw is None:
                return False
            pwd = pw.encode()
            report.add(INFO, where, f"password-protected; opened with password '{pw}'")
        for i in infos:
            name = i.filename.replace("\\", "/")
            problem = _unsafe(name)
            if problem:
                report.add(WARN, where, f"'{i.filename}' {problem}; not unpacked")
                continue
            if i.create_system == 3 and stat.S_ISLNK(i.external_attr >> 16):
                report.add(WARN, where, f"'{i.filename}' is a symbolic link; not unpacked")
                continue
            target = os.path.join(dest, name)
            try:
                if i.is_dir() or name.endswith("/"):
                    os.makedirs(target, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(i, pwd=pwd) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
            except zipfile.BadZipFile as e:
                report.add(WARN, where, f"'{i.filename}' is corrupted ({e})")
            except OSError as e:
                report.add(INFO, where, f"'{i.filename}' couldn't be written ({e.strerror})")
    return True


def _parse_slt(text):
    entries, cur = [], {}
    for line in text.splitlines():
        if not line.strip():
            if cur:
                entries.append(cur)
            cur = {}
        elif " = " in line:
            k, v = line.split(" = ", 1)
            cur[k.strip()] = v
    if cur:
        entries.append(cur)
    return [e for e in entries if "Path" in e]


def _extract_7z(path, dest, where, report, passwords):
    exe = shutil.which("7z") or shutil.which("7zz")
    if not exe:
        report.unchecked.append(f"{where}: 7-Zip isn't installed, so this archive couldn't be opened")
        return
    last = None
    for pw in passwords + [""]:
        listing = _run([exe, "l", "-slt", "-ba", f"-p{pw}", "--", path])
        if listing.returncode != 0:
            last = listing
            continue
        entries = _parse_slt(listing.stdout)
        for e in entries:
            problem = _unsafe(e["Path"])
            if problem:
                report.add(WARN, where, f"'{e['Path']}' {problem}")
        sizes = [(int(e.get("Size") or 0), int(e.get("Packed Size") or 0)) for e in entries]
        if _too_big(sizes, where, report):
            return
        shutil.rmtree(dest, ignore_errors=True)
        os.makedirs(dest)
        res = _run([exe, "x", "-y", "-bd", f"-p{pw}", f"-o{dest}", "--", path])
        out = res.stdout + res.stderr
        if res.returncode == 0:
            if pw and any(e.get("Encrypted") == "+" for e in entries):
                report.add(INFO, where, f"password-protected; opened with password '{pw}'")
            return
        if "Wrong password" in out or "Can not open encrypted archive" in out:
            last = res
            continue
        report.unchecked.append(f"{where}: 7-Zip hit errors unpacking it ({_last_line(res)}); "
                                "whatever it managed to unpack was still scanned")
        return
    if archive_type(path) == "rar" and shutil.which("unar"):
        for pw in passwords + [""]:
            res = _run(["unar", "-q", "-f", "-D", "-o", dest, "-p", pw, path])
            if res.returncode == 0:
                return
    report.unchecked.append(f"{where}: couldn't open it ({_last_line(last) if last else 'unknown error'}). "
                            "If it has a password, run again with --password")


def _sanitize(dest, root, report):
    """Removes links an archive tool may have created, so nothing points outside the folder."""
    real_root = os.path.realpath(root)
    for dirpath, dirs, files in os.walk(dest):
        for name in dirs + files:
            p = os.path.join(dirpath, name)
            rel = os.path.relpath(p, root)
            if os.path.islink(p):
                report.add(WARN, rel, f"is a link to {os.readlink(p)!r}; removed")
                os.unlink(p)
            elif os.path.isfile(p) and os.stat(p).st_nlink > 1:
                report.add(WARN, rel, "is a hard link to another file; removed")
                os.unlink(p)
            elif not os.path.realpath(p).startswith(real_root + os.sep):
                report.add(WARN, rel, "ended up outside the unpack folder")


def open_archive(path, dest, root, where, report, passwords, depth=0):
    """Unpacks `path` into `dest`, then any archives inside it. Returns how many archives were opened."""
    os.makedirs(dest, exist_ok=True)
    kind = archive_type(path)
    handled = False
    if kind == "zip":
        try:
            check_zip(path, where, report)
            handled = _extract_zip(path, dest, where, report, passwords)
        except zipfile.BadZipFile as e:
            report.add(INFO, where, f"Python couldn't read the zip ({e}); trying 7-Zip")
        except NotImplementedError:
            pass  # AES encryption or a compression method only 7-Zip knows
        if not handled:
            shutil.rmtree(dest, ignore_errors=True)
            os.makedirs(dest)
    if not handled:
        _extract_7z(path, dest, where, report, passwords)
    _sanitize(dest, root, report)

    opened = 1
    nested = [os.path.join(d, f) for d, _, fs in os.walk(dest) for f in fs]
    for p in sorted(n for n in nested if archive_type(n)):
        rel = os.path.relpath(p, root)
        if depth + 1 >= MAX_DEPTH:
            report.unchecked.append(f"{rel}: archive nested more than {MAX_DEPTH} levels deep; not opened")
            continue
        opened += open_archive(p, p + ".contents", root, rel, report, passwords, depth + 1)
    return opened
