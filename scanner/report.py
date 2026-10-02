"""Collects what each check finds, decides the verdict, and writes the report."""
from dataclasses import asdict, dataclass, field

DANGER, WARN, INFO = "danger", "warn", "info"
_ORDER = {DANGER: 0, WARN: 1, INFO: 2}
_LABEL = {DANGER: "DANGER", WARN: "WARNING", INFO: "NOTE"}
MAX_LISTED_FINDINGS = 300


def human(n):
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


@dataclass
class Finding:
    level: str
    where: str
    message: str


@dataclass
class Report:
    name: str
    sha256: str = ""
    md5: str = ""
    size: int = 0
    findings: list = field(default_factory=list)
    checks: list = field(default_factory=list)      # (check, result)
    sections: list = field(default_factory=list)    # (heading, markdown body)
    files: list = field(default_factory=list)       # (path, size, type)
    code_files: list = field(default_factory=list)  # things that can run: programs, scripts, macros
    unchecked: list = field(default_factory=list)   # parts that couldn't be opened or scanned

    def add(self, level, where, message):
        finding = Finding(level, where, message)
        if finding not in self.findings:
            self.findings.append(finding)

    def check(self, name, result):
        self.checks.append((name, result))

    def section(self, heading, body):
        self.sections.append((heading, body))

    def verdict(self):
        levels = {f.level for f in self.findings}
        if DANGER in levels:
            return "MALWARE DETECTED", "An antivirus signature matched. Don't open or use this."
        if WARN in levels:
            return "SUSPICIOUS", "Something here needs a closer look before you use it."
        if self.unchecked:
            return "NOT FULLY CHECKED", "Part of it couldn't be opened or scanned, so a clean result isn't guaranteed."
        if self.code_files:
            return ("NO MALWARE FOUND, BUT CONTAINS PROGRAM CODE",
                    "Nothing known-bad turned up, but programs and scripts can't be proven safe by scanning alone.")
        return "CLEAN", "Data files only: nothing that can run on its own, and every check passed."

    def markdown(self, include_files=True):
        label, why = self.verdict()
        out = [f"# Scan report: {self.name}", "", f"**Verdict: {label}** — {why}", "",
               "| | |", "|---|---|",
               f"| SHA-256 | `{self.sha256}` |", f"| MD5 | `{self.md5}` |", f"| Size | {human(self.size)} |",
               "", "## Findings", ""]
        grouped = {}  # the same message in many files becomes one line
        for f in sorted(self.findings, key=lambda f: _ORDER[f.level]):
            grouped.setdefault((f.level, f.message), []).append(f.where)
        for (level, message), places in list(grouped.items())[:MAX_LISTED_FINDINGS]:
            where = ", ".join(f"`{p}`" for p in places[:3])
            if len(places) > 3:
                where += f" and {len(places) - 3} more ({len(places)} files)"
            out.append(f"- **{_LABEL[level]}** {where}: {message}")
        if len(grouped) > MAX_LISTED_FINDINGS:
            out.append(f"- …and {len(grouped) - MAX_LISTED_FINDINGS} more (see report.json)")
        if not grouped:
            out.append("Nothing found.")
        if self.unchecked:
            out += ["", "**Couldn't check:**"] + [f"- {u}" for u in self.unchecked]
        if self.code_files:
            out += ["", "**Things that can run (programs, scripts, macros):**"]
            out += [f"- `{c}`" for c in self.code_files[:100]]
        out += ["", "## Checks", "", "| Check | Result |", "|---|---|"]
        out += [f"| {_cell(n)} | {_cell(r)} |" for n, r in self.checks]
        for heading, body in self.sections:
            out += ["", f"## {heading}", "", body]
        if include_files and self.files:
            out += ["", f"## All files ({len(self.files)})", "", "| File | Size | Type |", "|---|---|---|"]
            out += [f"| `{_cell(p)}` | {human(s)} | {_cell(t)} |" for p, s, t in self.files]
        return "\n".join(out) + "\n"

    def to_json(self):
        label, why = self.verdict()
        return {
            "name": self.name, "verdict": label, "explanation": why,
            "sha256": self.sha256, "md5": self.md5, "size": self.size,
            "findings": [asdict(f) for f in self.findings],
            "checks": self.checks, "unchecked": self.unchecked,
            "code_files": self.code_files, "files": self.files,
        }
