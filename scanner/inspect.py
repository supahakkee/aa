"""Works out what each unpacked file really is (by its contents, not its name) and looks
inside it for things that don't belong: hidden programs, commands, webhooks, extra data."""
import collections
import datetime
import mmap
import os
import re
import struct
import subprocess
import zlib

from .archive import archive_type
from .report import INFO, WARN

PROGRAM_EXT = {".exe", ".dll", ".sys", ".scr", ".cpl", ".ocx", ".com", ".drv", ".efi", ".msi", ".msp",
               ".so", ".dylib", ".pyd", ".node", ".asi", ".xll", ".class", ".dex", ".elf", ".mui", ".ax"}
SCRIPT_EXT = {".bat", ".cmd", ".ps1", ".psm1", ".psd1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
              ".hta", ".sh", ".bash", ".py", ".pyw", ".pyc", ".lua", ".rb", ".pl", ".php", ".ahk", ".au3",
              ".reg", ".inf", ".url", ".desktop", ".scf", ".jar", ".apk", ".appx", ".msix", ".chm",
              ".docm", ".xlsm", ".pptm", ".xlam", ".dotm", ".lnk"}
DOC_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf", ".jpg", ".jpeg",
           ".png", ".gif", ".bmp", ".webp", ".mp3", ".mp4", ".avi", ".mkv", ".mov", ".wav", ".ogg",
           ".zip", ".rar", ".7z", ".uasset", ".umap", ".pak", ".fbx", ".obj", ".blend", ".psd", ".tga",
           ".dds", ".unitypackage", ".html", ".htm", ".csv", ".json", ".xml", ".ini", ".cfg"}
PROXY_DLLS = {"dwmapi.dll", "xinput1_3.dll", "xinput1_4.dll", "xinput9_1_0.dll", "version.dll",
              "winmm.dll", "dinput8.dll", "d3d9.dll", "d3d11.dll", "d3d12.dll", "dxgi.dll",
              "winhttp.dll", "dsound.dll", "opengl32.dll", "msacm32.dll", "wininet.dll"}
CODE_KINDS = {"program", "script", "shortcut", "macro"}

_BIDI = re.compile("[‪-‮⁦-⁩‎‏]")
_DOS_STUB = b"This program cannot be run in DOS mode"
_URL = re.compile(rb"(?i)\b(?:https?|ftp)://[a-z0-9.-]+(?::\d+)?(?:/[^\s\"'<>\x00-\x1f]{0,150})?")
_BENIGN_HOSTS = re.compile(
    r"(?i)(^|\.)(digicert|verisign|symantec|symcb|symcd|thawte|globalsign|sectigo|comodoca|usertrust|"
    r"entrust|letsencrypt|godaddy|microsoft|windows|w3|xmlsoap|adobe|apple|unrealengine|epicgames|"
    r"unity3d|unity|apache|gnu|opensource|python|mozilla|openssl|khronos|nvidia|amd|intel|github|"
    r"ietf|iana|ocsp\.[a-z0-9-]+|crl\.[a-z0-9-]+)\.(com|net|org|io|be)$")

# (pattern, what it means, strong): strong ones are warnings even inside a program file,
# the rest are only warnings in data files and scripts, where they have no business being.
_PATTERNS = [(re.compile(p, re.I), what, strong) for p, what, strong in [
    (rb"discord(?:app)?\.com/api/webhooks/", "a Discord webhook (a common way to send stolen data)", True),
    (rb"api\.telegram\.org/bot", "a Telegram bot address (a common way to send stolen data)", True),
    (rb"\\(?:Google\\Chrome|Microsoft\\Edge|BraveSoftware\\Brave-Browser)\\User Data|\\Login Data\b|"
     rb"\\Local Storage\\leveldb|wallet\.dat|\\Exodus\\exodus\.wallet|\\Electrum\\wallets",
     "paths to saved browser passwords, Discord tokens or crypto wallets", True),
    (rb"Add-MpPreference|Set-MpPreference|DisableRealtimeMonitoring", "commands that switch off or bypass Windows Defender", True),
    (rb"vssadmin(?:\.exe)?\s+delete\s+shadows", "deleting Windows backups (ransomware behaviour)", True),
    (rb"powershell(?:\.exe)?[^\n]{0,80}\s-(?:e|en|enc|encodedcommand)\s+[A-Za-z0-9+/=]{16}", "PowerShell running a hidden (encoded) command", True),
    (rb"pastebin\.com/raw|paste\.ee/r/|hastebin\.com/raw|rentry\.co/[a-z0-9]+/raw", "downloading from a paste site", False),
    (rb"https?://\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?/", "a web address that is a bare IP number", False),
    (rb"\bIEX\s*[(\$'\"]|\|\s*IEX\b|Invoke-Expression", "PowerShell running text as code", False),
    (rb"DownloadString|DownloadFile|Invoke-WebRequest|Start-BitsTransfer|URLDownloadToFile", "downloading something from the internet", False),
    (rb"FromBase64String", "decoding hidden (base64) content", False),
    (rb"certutil(?:\.exe)?\s+[^\n]{0,40}-(?:urlcache|decode)", "certutil used to download or decode files", False),
    (rb"bitsadmin(?:\.exe)?\s+[^\n]{0,20}/transfer", "bitsadmin used to download files", False),
    (rb"mshta(?:\.exe)?\s+[\"']?(?:https?|javascript|vbscript):", "mshta running remote or inline script", False),
    (rb"regsvr32[^\n]{0,40}/i:https?", "regsvr32 loading code from the internet", False),
    (rb"schtasks(?:\.exe)?\s+/create", "creating a scheduled task (to run again later)", False),
    (rb"CurrentVersion\\\\?Run(?:Once)?\b", "making something start with Windows", False),
    (rb"(?:curl|wget)\s[^\n|]{0,200}\|\s*(?:ba)?sh\b", "downloading and running a shell script", False),
    (rb"\bos\.execute\s*\(|\bio\.popen\s*\(", "a Lua script running system commands", False),
    (rb"\bsubprocess\.(?:Popen|call|run)\b|\bos\.system\s*\(", "a Python script running system commands", False),
]]


class Entry:
    def __init__(self, root, path):
        self.path = path
        self.rel = os.path.relpath(path, root)
        self.name = os.path.basename(path)
        self.ext = os.path.splitext(self.name)[1].lower()
        self.size = os.path.getsize(path)
        self.kind, self.label = sniff(path, self.ext)


def _read_head_tail(path, n=0x8010):
    with open(path, "rb") as f:
        head = f.read(n)
        f.seek(max(0, os.path.getsize(path) - 512))
        tail = f.read()
    return head, tail


def _looks_like_text(head):
    if not head or b"\x00" in head[:8192]:
        return False
    try:
        head[:8192].decode("utf-8")
        return True
    except UnicodeDecodeError as e:
        if e.start > 8180:
            return True  # a multi-byte character cut off at the end of the sample
        printable = sum(32 <= b < 127 or b in b"\r\n\t" for b in head[:8192])
        return printable / min(len(head), 8192) > 0.95


def sniff(path, ext):
    """Returns (kind, label) from the file's first bytes; the extension only breaks ties."""
    head, tail = _read_head_tail(path)
    if head[:2] == b"MZ":
        if len(head) >= 0x40:
            pe = struct.unpack_from("<I", head, 0x3C)[0]
            if head[pe:pe + 4] == b"PE\x00\x00":
                return "program", "Windows program (PE)"
        return "program", "DOS/Windows executable (MZ)"
    if head[:4] == b"\x7fELF":
        return "program", "Linux program (ELF)"
    if head[:4] in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe"):
        return "program", "macOS program (Mach-O)"
    if head[:4] == b"\xca\xfe\xba\xbe":
        return "program", "Java class" if ext == ".class" else "macOS program (Mach-O)"
    if head[:4] == b"dex\n":
        return "program", "Android program (dex)"
    if head[:8] == b"\x4c\x00\x00\x00\x01\x14\x02\x00":
        return "shortcut", "Windows shortcut (.lnk)"
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        if ext in (".msi", ".msp"):
            return "program", "Windows installer (MSI)"
        if b"V\x00B\x00A\x00" in head or b"_VBA_PROJECT" in head or ext in (".doc", ".xls", ".ppt", ".dot", ".xlt"):
            return "macro", "Office document (old format, can contain macros)"
        return "data", "OLE compound file"
    if head[:4] == b"ITSF":
        return "script", "Compiled HTML help (.chm)"
    if head[:4] == b"\xc1\x83\x2a\x9e":
        return "unreal", "Unreal Engine package"
    if ext in (".uexp", ".ubulk", ".uptnl", ".ucas", ".utoc"):
        return "unreal-data", f"Unreal Engine data ({ext})"
    if b"\xe1\x12\x6f\x5a" in tail:
        return "unreal-data", "Unreal Engine .pak archive"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image", "PNG image"
    if head[:3] == b"\xff\xd8\xff":
        return "image", "JPEG image"
    for sig, label in ((b"GIF8", "GIF image"), (b"DDS ", "DDS texture"), (b"8BPS", "Photoshop file"),
                       (b"\x76\x2f\x31\x01", "EXR image"), (b"#?RADIANCE", "HDR image"), (b"BM", "BMP image"),
                       (b"II*\x00", "TIFF image"), (b"MM\x00*", "TIFF image"), (b"OggS", "OGG audio"),
                       (b"fLaC", "FLAC audio"), (b"ID3", "MP3 audio"), (b"Kaydara FBX Binary", "FBX 3D model"),
                       (b"glTF", "glTF 3D model"), (b"BLENDER", "Blender file"), (b"UnityFS", "Unity asset bundle"),
                       (b"%PDF", "PDF document"), (b"\x00\x00\x01\x00", "Windows icon")):
        if head.startswith(sig):
            kind = "image" if "image" in label or "texture" in label or "Photoshop" in label else \
                   "document" if "PDF" in label else "media" if "audio" in label else "data"
            return kind, label
    if head[:4] == b"RIFF":
        return "media", {b"WAVE": "WAV audio", b"WEBP": "WEBP image", b"AVI ": "AVI video"}.get(head[8:12], "RIFF media")
    if head[4:8] == b"ftyp":
        return "media", "MP4/MOV video"
    kind = archive_type(path)
    if kind:
        return "archive", f"{kind} archive"
    if _looks_like_text(head):
        if head[:2] == b"#!" or ext in SCRIPT_EXT:
            return "script", f"script ({ext or 'shebang'})"
        if head.lstrip()[:18].lower() == b"[internetshortcut]":
            return "shortcut", "Internet shortcut (.url)"
        return "text", f"text ({ext or 'no extension'})"
    if ext == ".pyc":
        return "script", "compiled Python (.pyc)"
    return "data", "binary data"


def file_description(path):
    try:
        return subprocess.run(["file", "-b", path], capture_output=True, text=True).stdout.strip()[:80]
    except OSError:
        return ""


def check_name(e, report):
    if _BIDI.search(e.name):
        report.add(WARN, e.rel, "the name contains hidden right-to-left characters (used to fake the extension)")
    parts = e.name.lower().split(".")
    if len(parts) >= 3:
        last, prev = "." + parts[-1], "." + parts[-2].strip()
        if (last in PROGRAM_EXT or last in SCRIPT_EXT) and prev in DOC_EXT:
            report.add(WARN, e.rel, f"double extension: it looks like a {prev} file but is really {last}")
    if re.search(r"\s{5,}\.\w+$", e.name):
        report.add(WARN, e.rel, "lots of spaces before the extension (hides the real file type)")
    if e.name.lower() == "vbaproject.bin":
        report.add(INFO, e.rel, "Office macros (code that runs when the document is opened with macros enabled)")


def check_disguise(e, report):
    if e.kind == "program" and e.ext not in PROGRAM_EXT:
        report.add(WARN, e.rel, f"is a {e.label} but is named '{e.ext or 'no extension'}' (a disguised program)")
    elif e.kind == "shortcut" and e.ext not in (".lnk", ".url"):
        report.add(WARN, e.rel, f"is a {e.label} but is named '{e.ext or 'no extension'}'")
    elif e.ext in (".uasset", ".umap") and e.kind != "unreal":
        report.add(WARN, e.rel, f"is named like an Unreal file but is actually {e.label}")


def _collapse_utf16(data):
    return re.sub(rb"([\x20-\x7e])\x00", rb"\1", data)


def scan_bytes(data, where, report, in_program=False):
    """Searches raw bytes for commands, webhooks, hidden programs and web addresses.
    Returns how many suspicious things it found."""
    hits = 0
    texts = [data]
    if in_program and len(data) < 64 << 20:
        texts.append(_collapse_utf16(data))
    seen = set()
    for text in texts:
        for rx, what, strong in _PATTERNS:
            if what in seen:
                continue
            m = rx.search(text)
            if m:
                seen.add(what)
                level = WARN if (strong or not in_program) else INFO
                sample = m.group(0)[:80].decode("latin-1")
                report.add(level, where, f"contains {what}: {sample!r}")
                hits += level == WARN

    stub = data.find(_DOS_STUB, 0x200 if in_program else 0)
    if stub >= 0:
        if in_program:
            report.add(INFO, where, "has another program embedded inside it (normal for installers)")
        else:
            report.add(WARN, where, f"has a Windows program hidden inside it (at byte {stub:,})")
            hits += 1
    if not in_program:
        elf = re.search(rb"\x7fELF[\x01\x02][\x01\x02]\x01", data)
        if elf and elf.start() > 0:
            report.add(WARN, where, f"has a Linux program hidden inside it (at byte {elf.start():,})")
            hits += 1

    hosts = collections.OrderedDict()
    for text in texts:
        for m in _URL.finditer(text):
            url = m.group(0).decode("latin-1")
            host = url.split("/")[2].split(":")[0].lower()
            if not _BENIGN_HOSTS.search(host):
                hosts.setdefault(host, url)
    if hosts:
        shown = list(hosts.values())[:8]
        more = f" (+{len(hosts) - 8} more)" if len(hosts) > 8 else ""
        report.add(INFO, where, "web addresses inside: " + ", ".join(shown) + more)
    return hits


def scan_file(e, report):
    if e.size == 0:
        return 0
    with open(e.path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
        return scan_bytes(m, e.rel, report, in_program=e.kind == "program")


def _trailing_level(trailing):
    hidden = (trailing[:2] == b"MZ" or trailing[:4] in (b"PK\x03\x04", b"Rar!", b"7z\xbc\xaf")
              or _DOS_STUB in trailing or b"<script" in trailing.lower())
    return WARN if hidden else INFO


def check_png(data, where, report):
    """Walks the PNG's chunks; real images end at IEND with nothing after it."""
    o, bad_crc, odd = 8, 0, set()
    standard = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"cHRM", b"gAMA", b"iCCP", b"sBIT", b"sRGB",
                b"tEXt", b"zTXt", b"iTXt", b"bKGD", b"hIST", b"pHYs", b"sPLT", b"tIME", b"eXIf", b"acTL",
                b"fcTL", b"fdAT", b"cICP", b"mDCv", b"cLLi", b"oFFs", b"pCAL", b"sCAL"}
    while o + 12 <= len(data):
        n = struct.unpack_from(">I", data, o)[0]
        ctype = bytes(data[o + 4:o + 8])
        if o + 12 + n > len(data):
            report.add(INFO, where, "PNG image is cut off (truncated)")
            return False
        if zlib.crc32(data[o + 4:o + 8 + n]) & 0xFFFFFFFF != struct.unpack_from(">I", data, o + 8 + n)[0]:
            bad_crc += 1
        if ctype not in standard and n > 1024:
            odd.add(ctype.decode("latin-1"))
        o += 12 + n
        if ctype == b"IEND":
            break
    else:
        report.add(INFO, where, "PNG image has no end marker")
        return False
    if bad_crc:
        report.add(INFO, where, f"PNG image has {bad_crc} corrupted chunk(s)")
    if odd:
        report.add(INFO, where, f"PNG image has large non-standard chunks: {', '.join(sorted(odd))}")
    trailing = bytes(data[o:])
    if trailing.strip(b"\x00"):
        report.add(_trailing_level(trailing), where, f"{len(trailing):,} bytes of extra data after the end of the image")
        return False
    return not bad_crc


def check_jpeg(data, where, report):
    end = data.rfind(b"\xff\xd9")
    if end < 0:
        report.add(INFO, where, "JPEG image has no end marker")
        return False
    trailing = bytes(data[end + 2:])
    if trailing.strip(b"\x00"):
        report.add(_trailing_level(trailing), where, f"{len(trailing):,} bytes of extra data after the end of the image")
        return False
    return True


def check_image(e, report):
    if e.label not in ("PNG image", "JPEG image") or e.size == 0:
        return None
    with open(e.path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
        return (check_png if e.label == "PNG image" else check_jpeg)(m, e.rel, report)


def check_pdf(e, report):
    with open(e.path, "rb") as f:
        data = f.read()
    if re.search(rb"/Launch\b", data):
        report.add(WARN, e.rel, "PDF tries to launch a program when opened")
    if re.search(rb"/JavaScript\b|/JS\b", data):
        report.add(INFO, e.rel, "PDF contains JavaScript")
        report.code_files.append(f"{e.rel} (PDF with JavaScript)")
    if re.search(rb"/EmbeddedFile\b", data):
        report.add(INFO, e.rel, "PDF has files embedded inside it")


_PACKERS = {"UPX0": "UPX", "UPX1": "UPX", ".themida": "Themida", ".winlice": "Themida", ".vmp0": "VMProtect",
            ".vmp1": "VMProtect", ".enigma1": "Enigma", ".aspack": "ASPack", ".MPRESS1": "MPRESS",
            ".petite": "Petite", "PEC2": "PECompact", ".nsp0": "NsPack", ".boom": "Boomerang"}
_API_GROUPS = [
    ({"VirtualAllocEx", "WriteProcessMemory", "CreateRemoteThread"}, "injects code into other programs", WARN),
    ({"CryptUnprotectData"}, "can decrypt saved browser passwords (Windows DPAPI)", WARN),
    ({"SetWindowsHookExA", "GetAsyncKeyState"}, "watches keyboard input", INFO),
    ({"SetWindowsHookExW", "GetAsyncKeyState"}, "watches keyboard input", INFO),
    ({"URLDownloadToFileA"}, "downloads files from the internet", INFO),
    ({"URLDownloadToFileW"}, "downloads files from the internet", INFO),
    ({"InternetOpenUrlA"}, "connects to the internet", INFO), ({"InternetOpenUrlW"}, "connects to the internet", INFO),
    ({"WinHttpOpen"}, "connects to the internet", INFO),
    ({"ShellExecuteA"}, "can start other programs", INFO), ({"ShellExecuteW"}, "can start other programs", INFO),
    ({"CreateProcessA"}, "can start other programs", INFO), ({"CreateProcessW"}, "can start other programs", INFO),
    ({"WinExec"}, "can start other programs", INFO),
]


def analyze_pe(e, report):
    """Reads a Windows program's headers. Returns a table row, or None if it couldn't be read."""
    try:
        import pefile
    except ImportError:
        report.unchecked.append(f"{e.rel}: pefile isn't installed, so the program's details weren't read")
        return None
    try:
        pe = pefile.PE(e.path)
    except Exception as ex:  # pefile raises many kinds of errors on malformed files
        report.add(INFO, e.rel, f"Windows program headers couldn't be read ({ex.__class__.__name__}); malformed or not really a program")
        return None
    with pe:
        fh, oh = pe.FILE_HEADER, pe.OPTIONAL_HEADER
        arch = {0x14C: "32-bit", 0x8664: "64-bit", 0xAA64: "ARM64"}.get(fh.Machine, hex(fh.Machine))
        kind = "DLL" if fh.Characteristics & 0x2000 else "EXE"
        dirs = oh.DATA_DIRECTORY
        dotnet = len(dirs) > 14 and dirs[14].VirtualAddress != 0
        signed = len(dirs) > 4 and dirs[4].Size > 0
        try:
            built = datetime.datetime.fromtimestamp(fh.TimeDateStamp, datetime.timezone.utc).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            built = "?"
        notes = []
        names = {s.Name.rstrip(b"\x00").decode("latin-1") for s in pe.sections}
        packers = sorted({p for s, p in _PACKERS.items() if s in names})
        if packers:
            report.add(WARN, e.rel, f"is packed with {', '.join(packers)}, which hides its code (unusual for a mod)")
            notes.append("packed: " + ", ".join(packers))
        dense = [s.Name.rstrip(b"\x00").decode("latin-1") for s in pe.sections
                 if s.SizeOfRawData > 4096 and s.get_entropy() > 7.2]
        if dense and not packers:
            report.add(INFO, e.rel, f"has compressed or encrypted sections ({', '.join(dense)})")
            notes.append("encrypted/compressed sections")
        apis = set()
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            apis.update(i.name.decode("latin-1") for i in entry.imports if i.name)
        seen = set()
        for group, what, level in _API_GROUPS:
            if group <= apis and what not in seen:
                seen.add(what)
                report.add(level, e.rel, f"program {what}")
                notes.append(what)
        overlay = pe.get_overlay_data_start_offset()
        if overlay:
            report.add(INFO, e.rel, f"{e.size - overlay:,} bytes of extra data appended after the program (common for installers)")
        if e.name.lower() in PROXY_DLLS:
            report.add(INFO, e.rel, "is named like a Windows system DLL: dropped into a game folder it loads automatically "
                                    "when the game starts (normal for mod loaders like UE4SS, but it runs with full access)")
            notes.append("auto-loading DLL name")
        if not signed:
            notes.append("not signed")
    return (e.rel, f"{arch} {kind}" + (" (.NET)" if dotnet else ""), "yes" if signed else "no", built,
            "; ".join(notes) or "-")
