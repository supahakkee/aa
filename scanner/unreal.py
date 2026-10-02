"""Reads Unreal Engine packages (.uasset/.umap) field by field, so we can list exactly what's
inside, prove every byte is accounted for, and unpack the compressed data text searches can't see."""
import collections
import os
import re
import struct
import zlib

from . import inspect
from .report import INFO, WARN

TAG = 0x9E2A83C1
_TAG64 = struct.pack("<q", TAG)
_FILTER_EDITOR_ONLY = 0x80000000
_MAX_INFLATE = 512 << 20      # per compressed stream
_MAX_SCAN_FILE = 256 << 20    # files bigger than this aren't searched for compressed data

# Names that mean an asset can do more than hold art. Matched exactly against each package's name table.
_RISKY_NAMES = {
    "ExecutePythonCommand": (WARN, "runs Python code inside the Unreal Editor"),
    "ExecutePythonCommandEx": (WARN, "runs Python code inside the Unreal Editor"),
    "ExecutePythonScript": (WARN, "runs Python code inside the Unreal Editor"),
    "PythonScriptLibrary": (WARN, "runs Python code inside the Unreal Editor"),
    "/Script/PythonScriptPlugin": (WARN, "uses the Python scripting plugin"),
    "LaunchProcess": (WARN, "can start other programs on your computer"),
    "CreateProc": (WARN, "can start other programs on your computer"),
    "RunProcess": (WARN, "can start other programs on your computer"),
    "ExecuteProcess": (WARN, "can start other programs on your computer"),
    "LaunchURL": (INFO, "can open a web page"),
    "ExecuteConsoleCommand": (INFO, "can run engine console commands"),
    "/Script/Blutility": (INFO, "is an Editor Utility (a script that runs inside the Unreal Editor)"),
    "EditorUtilityWidgetBlueprint": (INFO, "is an Editor Utility (a script that runs inside the Unreal Editor)"),
    "EditorUtilityBlueprint": (INFO, "is an Editor Utility (a script that runs inside the Unreal Editor)"),
    "/Script/HTTP": (INFO, "can make web requests"),
    "/Script/VaRest": (INFO, "can make web requests"),
}


class _Reader:
    def __init__(self, data):
        self.b, self.o = data, 0

    def take(self, n):
        if n < 0 or self.o + n > len(self.b):
            raise ValueError("read past the end of the header")
        v = self.b[self.o:self.o + n]
        self.o += n
        return v

    def i32(self):
        return struct.unpack("<i", self.take(4))[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def i64(self):
        return struct.unpack("<q", self.take(8))[0]

    def count(self, limit=10_000_000):
        n = self.i32()
        if not 0 <= n <= limit:
            raise ValueError(f"implausible count {n}")
        return n

    def fstr(self):
        n = self.i32()
        if n == 0:
            return ""
        if n > 0:
            return self.take(n)[:-1].decode("latin-1")
        return self.take(-n * 2)[:-2].decode("utf-16-le", "replace")


class Package:
    """The parts of an FPackageFileSummary we need, plus the name, import and export tables."""

    def __init__(self, data):
        r = _Reader(data)
        if r.u32() != TAG:
            raise ValueError("not an Unreal package")
        legacy = r.i32()
        if not -8 <= legacy <= -2:
            raise ValueError(f"unknown package format {legacy}")
        if legacy != -4:
            r.i32()
        ue4 = r.i32()
        ue5 = r.i32() if legacy <= -8 else 0
        r.i32()  # licensee version
        if ue4 == 0 and ue5 == 0:
            raise ValueError("unversioned (cooked) package")
        self.ue4, self.ue5, self.legacy = ue4, ue5, legacy
        if -5 <= legacy <= -3:
            raise ValueError("very old custom-version format")
        r.take(r.count(10_000) * (8 if legacy == -2 else 20))
        if ue5 >= 1016:
            r.take(20)  # saved hash
        self.header_size = r.i32()
        self.folder = r.fstr()
        self.flags = r.u32()
        editor = not self.flags & _FILTER_EDITOR_ONLY
        self.name_count, self.name_offset = r.count(), r.i32()
        if ue5 >= 1008:
            r.i32(), r.i32()
        if editor and ue4 >= 516:
            r.fstr()
        if ue4 >= 459:
            r.i32(), r.i32()
        self.export_count, self.export_offset = r.count(), r.i32()
        self.import_count, self.import_offset = r.count(), r.i32()
        if ue5 >= 1015:
            r.take(16)
        if ue5 >= 1014:
            r.i32()
        r.i32()  # depends offset
        if ue4 >= 384:
            r.i32(), r.i32()
        if ue4 >= 510:
            r.i32()
        r.i32()  # thumbnail table offset
        if ue5 < 1016:
            r.take(16)
        if editor and ue4 >= 518:
            r.take(16 if ue4 >= 520 else 32)
        r.take(8 * r.count(100_000))  # generations
        self.saved_by = "?"
        if ue4 >= 336:
            major, minor, patch = struct.unpack("<HHH", r.take(6))
            r.u32()
            self.saved_by = f"{major}.{minor}.{patch} ({r.fstr()})"
        if ue4 >= 444:
            r.take(10), r.fstr()
        self.compression_flags = r.u32()
        self.compressed_chunks = r.count(100_000)
        r.take(16 * self.compressed_chunks)
        r.u32()  # package source
        self.cook_packages = [r.fstr() for _ in range(r.count(100_000))]
        if legacy > -7:
            r.i32()
        r.i32()  # asset registry offset
        self.bulk_start = r.i64()

        r.o = self.name_offset
        self.names = []
        for _ in range(self.name_count):
            self.names.append(r.fstr())
            if ue4 >= 504:
                r.take(4)

        def fname():
            i, number = r.i32(), r.i32()
            if not 0 <= i < len(self.names):
                raise ValueError("name index out of range")
            return self.names[i] + (f"_{number - 1}" if number else "")

        r.o = self.import_offset
        self.imports = []
        for _ in range(self.import_count):
            class_package, class_name = fname(), fname()
            r.i32()
            object_name = fname()
            if ue4 >= 520 and editor:
                fname()
            if ue5 >= 1003:
                r.i32()
            self.imports.append((class_package, class_name, object_name))

        r.o = self.export_offset
        self.exports = []
        for _ in range(self.export_count):
            class_index = r.i32()
            r.i32()
            if ue4 >= 508:
                r.i32()
            r.i32()
            name = fname()
            r.u32()
            size, offset = (r.i64(), r.i64()) if ue4 >= 511 else (r.i32(), r.i32())
            r.take(12)
            if ue5 < 1005:
                r.take(16)
            if ue5 >= 1006:
                r.i32()
            r.u32()
            if ue4 >= 365:
                r.i32()
            if ue4 >= 485:
                r.i32()
            if ue5 >= 1003:
                r.i32()
            if ue4 >= 507:
                r.take(20)
            if ue5 >= 1010:
                r.take(16)
            if class_index < 0 and -class_index <= len(self.imports):
                cls = self.imports[-class_index - 1][2]
            elif 0 < class_index <= len(self.exports):
                cls = self.exports[class_index - 1][0]
            else:
                cls = "Class"
            self.exports.append((name, cls, size, offset))


def _layout_problems(pkg, total_len, has_uexp):
    """Exports should sit back to back from the end of the header to the bulk data, with the
    package tag as the last 4 bytes. Anything else is data the package's own index doesn't explain."""
    problems = []
    pos = pkg.header_size
    for name, _, size, offset in sorted(pkg.exports, key=lambda e: e[3]):
        if offset != pos:
            what = "gap" if offset > pos else "overlap"
            problems.append(f"{what} of {abs(offset - pos):,} bytes before '{name}'")
        pos = offset + size
    end = total_len - 4 if has_uexp else pkg.bulk_start
    if not has_uexp and pkg.bulk_start <= 0:
        end = total_len - 4
    if pos != end:
        problems.append(f"objects end at byte {pos:,} but the next section starts at {end:,}")
    return problems


def _last4(path):
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - 4))
        return f.read()


def _inflate_at(mv, start):
    """Inflates the zlib stream at `start`. Returns (data, bytes consumed) or (None, 0)."""
    d = zlib.decompressobj()
    out, total, pos = [], 0, start
    while pos < len(mv):
        chunk = mv[pos:pos + (1 << 20)]
        pos += len(chunk)
        while True:
            try:
                piece = d.decompress(chunk, 16 << 20)
            except zlib.error:
                return None, 0
            out.append(piece)
            total += len(piece)
            if total > _MAX_INFLATE:
                return None, 0
            if d.eof:
                return b"".join(out), pos - start - len(d.unused_data)
            chunk = d.unconsumed_tail
            if not chunk:
                break
    return None, 0


def _ue_blocks(data):
    """Finds Unreal's compressed bulk-data blocks: a header (tag, chunk size, totals, per-chunk sizes)
    followed by separately compressed chunks. Yields (offset, end, payload or None if not zlib)."""
    mv = memoryview(data)
    for m in re.finditer(re.escape(_TAG64), data):
        o = m.start()
        try:
            chunk_size, total_c, total_u = struct.unpack_from("<qqq", data, o + 8)
        except struct.error:
            continue
        if not (0 < chunk_size <= 1 << 24 and 0 < total_c <= len(data) and 0 < total_u <= 1 << 31):
            continue
        n = -(-total_u // chunk_size)
        table = o + 32
        if table + 16 * n > len(data):
            continue
        sizes = [struct.unpack_from("<qq", data, table + 16 * i) for i in range(n)]
        if sum(c for c, _ in sizes) != total_c or sum(u for _, u in sizes) != total_u:
            continue
        pos, parts = table + 16 * n, []
        for c, _ in sizes:
            try:
                parts.append(zlib.decompress(mv[pos:pos + c]))
            except zlib.error:
                parts = None
                break
            pos += c
        yield o, table + 16 * n + total_c, (b"".join(parts) if parts is not None else None)


def unpack_compressed(data):
    """Returns ([(offset, payload)], unsupported_block_count)."""
    payloads, covered, unsupported = [], [], 0
    for start, end, payload in _ue_blocks(data):
        covered.append((start, end))
        if payload is None:
            unsupported += 1
        else:
            payloads.append((start, payload))
    mv = memoryview(data)
    skip_to = 0
    for m in re.finditer(rb"\x78[\x01\x5e\x9c\xda]", data):
        o = m.start()
        if o < skip_to or any(s <= o < e for s, e in covered):
            continue
        payload, used = _inflate_at(mv, o)
        if payload is not None and len(payload) >= 16:
            payloads.append((o, payload))
            skip_to = o + used
    return payloads, unsupported


def _payload_type(p):
    if p[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG image"
    if p[:3] == b"\xff\xd8\xff":
        return "JPEG image"
    if p[:2] == b"MZ" and b"This program cannot be run" in p[:1024]:
        return "Windows program"
    if p[:4] == b"\x7fELF":
        return "Linux program"
    if p[:4] in (b"PK\x03\x04", b"Rar!", b"7z\xbc\xaf"):
        return "archive"
    if p[:4] == b"\xc1\x83\x2a\x9e":
        return "Unreal package"
    return "raw data"


def check_unreal(entries, inflated_dir, report):
    packages = [e for e in entries if e.kind == "unreal"]
    by_path = {e.path: e for e in entries}
    classes, modules, refs, versions = collections.Counter(), collections.Counter(), set(), collections.Counter()
    parsed, layout_ok, partial, blueprint_files = 0, 0, [], []
    for e in packages:
        with open(e.path, "rb") as f:
            data = f.read()
        uexp = os.path.splitext(e.path)[0] + ".uexp"
        has_uexp = uexp in by_path
        total = len(data) + (by_path[uexp].size if has_uexp else 0)
        try:
            pkg = Package(data)
        except (ValueError, struct.error, UnicodeDecodeError) as ex:
            partial.append(f"{e.rel} ({ex})")
            continue
        parsed += 1
        versions[pkg.saved_by] += 1
        for _, cls, _, _ in pkg.exports:
            classes[cls] += 1
        for class_package, class_name, object_name in pkg.imports:
            if class_name == "Package":
                if object_name.startswith("/Script/"):
                    modules[object_name] += 1
                else:
                    refs.add(object_name)
        names = set(pkg.names)
        for name, (level, what) in _RISKY_NAMES.items():
            if name in names:
                report.add(level, e.rel, f"Unreal asset that {what} ('{name}')")
        if any(n.startswith("K2Node_") for n in names):
            blueprint_files.append(e.rel)
        if pkg.compression_flags or pkg.compressed_chunks:
            report.add(INFO, e.rel, "whole-package compression is set (very unusual)")
        if pkg.cook_packages:
            report.add(INFO, e.rel, f"lists extra packages to cook: {pkg.cook_packages[:5]}")

        problems = _layout_problems(pkg, total, has_uexp)
        tail = _last4(uexp) if has_uexp else data[-4:]
        if tail != struct.pack("<I", TAG):
            problems.append("missing the end-of-package tag")
        if not problems:
            layout_ok += 1
        elif pkg.ue5 or has_uexp:
            partial.append(f"{e.rel} (layout not verified for this newer/cooked format: {problems[0]})")
        else:
            for p in problems:
                report.add(WARN, e.rel, f"data not explained by the package's own index: {p} (hidden data?)")

    if blueprint_files:
        report.add(INFO, f"{len(blueprint_files)} file(s)", "contain Blueprint scripting, which runs only inside "
                   "Unreal: " + ", ".join(blueprint_files[:5]) + (" …" if len(blueprint_files) > 5 else ""))
    if partial:
        report.add(INFO, f"{len(partial)} file(s)", "couldn't be fully read by the Unreal checker "
                   "(newer or cooked format, not a sign of malware); the other checks still covered them: "
                   + "; ".join(partial[:5]) + (" …" if len(partial) > 5 else ""))

    # Compressed data inside Unreal files (and unknown binaries) is invisible to text searches; unpack and scan it.
    targets = [e for e in entries if e.kind in ("unreal", "unreal-data", "data")]
    streams, kinds, unsupported, images_ok, images = 0, collections.Counter(), 0, 0, 0
    for e in targets:
        if e.size > _MAX_SCAN_FILE:
            report.unchecked.append(f"{e.rel}: too large ({e.size >> 20} MB) to search for compressed data inside")
            continue
        with open(e.path, "rb") as f:
            data = f.read()
        payloads, bad = unpack_compressed(data)
        unsupported += bad
        for offset, payload in payloads:
            streams += 1
            ptype = _payload_type(payload)
            kinds[ptype] += 1
            where = f"{e.rel} @ {offset:,}"
            name = e.rel.replace(os.sep, "__")[-150:] + f".{offset}.bin"
            with open(os.path.join(inflated_dir, name), "wb") as out:
                out.write(payload)
            if ptype in ("Windows program", "Linux program", "archive"):
                report.add(WARN, where, f"a hidden {ptype} is tucked inside compressed data")
            elif ptype == "PNG image":
                images += 1
                images_ok += inspect.check_png(payload, where, report)
            elif ptype == "JPEG image":
                images += 1
                images_ok += inspect.check_jpeg(payload, where, report)
            inspect.scan_bytes(payload, where, report)
    if unsupported:
        report.add(INFO, f"{unsupported} block(s)", "of compressed data use a format this tool can't unpack "
                   "(e.g. Oodle); they were scanned as-is but not unpacked")

    if packages:
        report.check("Unreal package structure",
                     f"{parsed}/{len(packages)} read field by field; {layout_ok} fully accounted for, byte for byte")
    if targets:
        detail = ", ".join(f"{n} {k}" for k, n in kinds.most_common())
        report.check("Compressed data inside files",
                     f"{streams} sections unpacked and scanned" + (f" ({detail})" if detail else "")
                     + (f"; {images_ok}/{images} embedded images valid with nothing hidden" if images else ""))
    if packages:
        lines = [f"- Saved by engine version: " + ", ".join(f"{v} ×{n}" for v, n in versions.most_common()),
                 "- What the files contain (object types): " +
                 ", ".join(f"{c} ×{n}" for c, n in classes.most_common(40)) + (" …" if len(classes) > 40 else ""),
                 "- Engine code modules referenced: " + (", ".join(sorted(modules)) or "none")]
        outside = sorted(r for r in refs if not r.startswith("/Engine/") and not r.startswith("/Game/"))
        if outside:
            lines.append("- Assets referenced from plugins or other mounts: " + ", ".join(outside[:20]))
        report.section("Unreal Engine packages", "\n".join(lines))
