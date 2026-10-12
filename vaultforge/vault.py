"""Vault reading: frontmatter, headings, wikilinks, link resolution."""
from __future__ import annotations

import re
from pathlib import Path

NOTE_EXT = (".md", ".canvas", ".base")
SKIP_DIRS = {".obsidian", ".trash", "Templates", "index", ".git"}

FM_OPEN = re.compile(r"^---\s*$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
WIKILINK = re.compile(r"(!?)\[\[([^\]\|#]+)(#[^\]\|]+)?(\|[^\]]+)?\]\]")
FRONTMATTER_AREA = re.compile(r"\[\[([^\]\|#]+)")
DATE_OK = re.compile(r"^\d{4}-\d{2}-\d{2}$")

TYPE_VOCAB = {
    "note", "moc", "project", "area", "resource", "content", "daily", "meeting", "decision",
}
STATUS_VOCAB = {
    "inbox", "idea", "draft", "active", "paused", "done", "published", "archived", "logged",
}
REQUIRED_KEYS = ("type", "status", "created", "updated", "priority")


FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`\n]*`")


def strip_code(text: str) -> str:
    """Blank out fenced blocks and inline code spans, keeping every line number intact."""
    out, in_fence = [], False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else INLINE_CODE.sub("", line))
    return "\n".join(out)


def parse_scalar(raw: str):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [part.strip().strip('"').strip("'") for part in inner.split(",") if part.strip()]
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    if raw in ("true", "false"):
        return raw == "true"
    return raw


def parse_frontmatter(text: str):
    """Return (frontmatter dict, body, error string or None)."""
    lines = text.splitlines()
    if not lines or not FM_OPEN.match(lines[0]):
        return {}, text, "no frontmatter block"
    for index in range(1, len(lines)):
        if FM_OPEN.match(lines[index]):
            block = lines[1:index]
            body = "\n".join(lines[index + 1:])
            data = {}
            for line in block:
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                if ":" not in line:
                    continue
                key, _, value = line.partition(":")
                data[key.strip()] = parse_scalar(value)
            return data, body, None
    return {}, text, "frontmatter block never closed"


class Note:
    def __init__(self, path: Path, root: Path):
        self.abs = path
        self.path = str(path.relative_to(root))
        self.title = path.stem
        try:
            self.text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self.text = ""
        self.frontmatter, self.body, self.fm_error = parse_frontmatter(self.text)
        self.headings = []
        self.links = []
        self.embeds = []
        offset = self._body_offset()
        # links are read from prose only: fenced blocks and inline code spans are stripped first,
        # otherwise a documented example like `[[Note Name]]` counts as a broken link.
        link_text = strip_code(self.text)
        for number, line in enumerate(link_text.splitlines(), start=1):
            m = HEADING.match(line)
            if m and number > offset:
                self.headings.append({"level": len(m.group(1)), "text": m.group(2), "line": number})
            for embed, target, _anchor, _alias in WIKILINK.findall(line):
                target = target.strip()
                if not target:
                    continue
                if embed:
                    self.embeds.append({"target": target, "line": number})
                else:
                    self.links.append({"target": target, "line": number})
        self._offset = offset
        self.type = str(self.frontmatter.get("type", "") or "")
        self.status = str(self.frontmatter.get("status", "") or "")
        tags = self.frontmatter.get("tags", [])
        self.tags = [str(t).lstrip("#") for t in tags] if isinstance(tags, list) else []

    def _body_offset(self) -> int:
        lines = self.text.splitlines()
        if lines and FM_OPEN.match(lines[0]):
            for index in range(1, len(lines)):
                if FM_OPEN.match(lines[index]):
                    return index + 1
        return 0

    def first_paragraph(self, limit: int = 180) -> str:
        for line in self.body.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("![[") or line.startswith("|"):
                continue
            if line.startswith("-") and len(line) < 12:
                continue
            return re.sub(r"\s+", " ", line)[:limit]
        return ""

    def chunks(self):
        """Heading-level chunks with line ranges, for the search index."""
        out = []
        current = {"heading": self.title, "level": 0, "start": self._offset + 1, "lines": []}
        for number, line in enumerate(self.text.splitlines(), start=1):
            if number <= self._offset:
                continue
            m = HEADING.match(line)
            if m:
                out.append(current)
                current = {"heading": m.group(2), "level": len(m.group(1)), "start": number, "lines": []}
            else:
                current["lines"].append(line)
        out.append(current)
        result = []
        for chunk in out:
            body = "\n".join(chunk["lines"]).strip()
            if not body and chunk["level"] == 0:
                continue
            end = chunk["start"] + len(chunk["lines"]) + 1
            result.append({
                "path": self.path,
                "title": self.title,
                "heading": chunk["heading"],
                "level": chunk["level"],
                "start_line": chunk["start"],
                "end_line": end,
                "text": body,
            })
        return result


def load_vault(root: Path, include_templates: bool = False):
    notes = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        skip = SKIP_DIRS if not include_templates else (SKIP_DIRS - {"Templates"})
        if any(part in skip for part in rel.parts):
            continue
        if path.suffix not in NOTE_EXT:
            continue
        if path.name.startswith("."):
            continue
        notes.append(Note(path, root))
    return notes


def resolution_index(notes) -> dict:
    table = {}
    for note in notes:
        flat = str(note.path).replace("\\", "/")
        stem = Path(flat).stem
        for key in (flat, flat.rsplit(".", 1)[0], stem):
            table.setdefault(key, []).append(flat)
    return table


def resolve(target: str, table: dict):
    key = target.strip().replace("\\", "/")
    if key in table:
        return table[key]
    if key.endswith(NOTE_EXT):
        stem = Path(key).stem
        return table.get(stem, [])
    return table.get(Path(key).stem, [])


def area_name(value) -> str:
    if isinstance(value, str):
        m = FRONTMATTER_AREA.search(value)
        if m:
            return m.group(1).strip()
        return value.strip()
    return ""


def is_template(note) -> bool:
    return str(note.path).startswith("Templates/") or str(note.path) == "Templates"
