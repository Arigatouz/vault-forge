"""Ingest pass: turn repository documents and source code into real vault notes.

Deterministic, no model and no network. Documents become notes carrying their own section headings,
the opening lines of each section and the source line range. Source code becomes one outline note per
module listing the classes, interfaces, methods and exports with `file:line`, so a reader (or an agent)
can jump straight to the declaration instead of grepping.

The scan pass answers "what is this repository". This pass answers "what is in it".
"""
from __future__ import annotations

import re
from pathlib import Path

from . import util
from .util import info, warn
from .scan import DOTNET_EXCLUDE, SOURCE_EXT, fm_block

DOC_DIR = "03-Resources/Repo Docs"
CODE_DIR = "03-Resources/Code Outline"
DOCS_MOC = "03-Resources/Repo Docs.md"
CODE_MOC = "03-Resources/Code Outline.md"

MAX_FILE_BYTES = 200_000
MAX_FILES_PER_MODULE = 40
MAX_SYMBOLS_PER_FILE = 30
MAX_SECTIONS_PER_DOC = 25
GENERATED_SUFFIXES = ("Designer.cs", "ModelSnapshot.cs", "AssemblyInfo.cs")

LANG_BY_EXT = {
    ".cs": "csharp", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
    ".jsx": "javascript", ".mjs": "javascript", ".py": "python", ".sql": "sql",
}

# kind, name, line, signature
CS_TYPE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*(?:public|internal|private|protected|file)?[\w\s]*?"
                     r"\b(class|interface|record|enum|struct)\s+([A-Za-z_][\w<>,.]*)", re.M)
CS_MEMBER = re.compile(r"^\s{2,}(?:public|internal|protected|private)\s+"
                       r"(?:static\s+|async\s+|virtual\s+|override\s+|sealed\s+|partial\s+|readonly\s+)*"
                       r"[\w<>\[\],.?]+\s+([A-Za-z_]\w*)\s*\(", re.M)
TS_DECL = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
                     r"(function|class|interface|type|const|enum)\s+([A-Za-z_$][\w$]*)", re.M)
PY_DECL = re.compile(r"^(class|def|async def)\s+([A-Za-z_]\w*)", re.M)
SQL_DECL = re.compile(r"^\s*CREATE\s+(TABLE|VIEW|INDEX|SCHEMA|TYPE)\s+(?:IF NOT EXISTS\s+)?([\w.\"]+)",
                      re.M | re.I)


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _signature(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()[:110]


def module_key(rel: Path, repo: Path) -> str:
    """Which note a source file belongs to. A .NET project/namespace segment wins, then the nearest
    manifest directory, then `src/<area>`, then the top two path parts."""
    parts = list(rel.parts)
    for index, part in enumerate(parts):
        if part.startswith("CompanyAcademy.") or ".Modules." in part:
            return "/".join(parts[: index + 1])
    for candidate in reversed(parts[:-1]):
        folder = repo.joinpath(*parts[: parts.index(candidate) + 1])
        if (folder / "package.json").exists() or (folder / "pyproject.toml").exists():
            return "/".join(parts[: parts.index(candidate) + 1])
    if "src" in parts:
        return "/".join(parts[: parts.index("src") + 2])
    return "/".join(parts[:2]) if len(parts) > 2 else parts[0]


def extract_symbols(text: str, language: str):
    out = []
    if language == "csharp":
        pattern = [(CS_TYPE, 1, 2), (CS_MEMBER, 1, 1)]
    elif language in ("typescript", "javascript"):
        pattern = [(TS_DECL, 1, 2)]
    elif language == "python":
        pattern = [(PY_DECL, 1, 2)]
    elif language == "sql":
        pattern = [(SQL_DECL, 1, 2)]
    else:
        return out
    for regex, kind_group, name_group in pattern:
        for match in regex.finditer(text):
            kind = match.group(kind_group)
            name = match.group(name_group)
            line_number = _line_of(text, match.start())
            line = text.splitlines()[line_number - 1] if text.splitlines() else ""
            out.append({"kind": kind.strip(), "name": name, "line": line_number,
                        "signature": _signature(line)})
    out.sort(key=lambda item: (item["line"], item["name"]))
    # one entry per (kind, name, line); methods repeat across overloads at different lines, keep those
    seen, unique = set(), []
    for item in out:
        key = (item["kind"], item["name"], item["line"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:MAX_SYMBOLS_PER_FILE]


def doc_title(path: Path, text: str) -> str:
    first = re.search(r"^#\s+(.+)$", text, re.M)
    if first:
        return first.group(1).strip()[:80]
    return path.stem.replace("-", " ").replace("_", " ").strip().title()


def doc_note_text(path: Path, rel: str, text: str, project: str, area: str) -> str:
    title = doc_title(path, text)
    lines = text.splitlines()
    if title.lower().replace(" ", "") in (path.stem.lower().replace("-", "").replace("_", ""), ""):
        title = "%s %s" % (rel.split("/")[0].title() if "/" in rel else "Doc", path.stem)

    # sections: every H2 with its opening paragraph and line range
    sections = []
    current = None
    for number, line in enumerate(lines, start=1):
        if re.match(r"^##\s+", line):
            if current:
                sections.append(current)
            current = {"heading": re.sub(r"^#+\s*", "", line).strip(), "start": number, "body": []}
        elif current is not None:
            current["body"].append(line)
    if current:
        sections.append(current)

    rendered = []
    for section in sections[:MAX_SECTIONS_PER_DOC]:
        paragraph = []
        for line in section["body"]:
            stripped = line.strip()
            if not stripped:
                if paragraph:
                    break
                continue
            if stripped.startswith(("```", "|", ">", "!")):
                continue
            paragraph.append(stripped)
        text_block = util.one_line(" ".join(paragraph), 420)
        end = section["start"] + len(section["body"])
        rendered.append("### %s" % section["heading"])
        rendered.append("")
        if text_block:
            rendered.append(text_block)
        rendered.append("")
        rendered.append("_source: `%s` lines %d-%d_" % (rel, section["start"], max(end, section["start"] + 1)))
        rendered.append("")
    if len(sections) > MAX_SECTIONS_PER_DOC:
        rendered.append("_%d further sections in `%s`._" % (len(sections) - MAX_SECTIONS_PER_DOC, rel))
        rendered.append("")

    return "\n".join([
        fm_block("resource", "active", area, ["reference", "repo-doc"], "medium",
                 {"source": '"%s"' % rel, "source_url": '""', "confidence": "high"}),
        "# %s" % title,
        "",
        "Ingested from `%s` (%d lines, %d bytes) on %s by `vault-forge ingest`." % (
            rel, len(lines), len(text.encode("utf-8")), util.TODAY),
        "",
        *rendered,
        "## Related",
        "",
        "- [[%s]]" % project,
        "- [[Repo Docs]]",
    ])


def code_label(module: str) -> str:
    """The single canonical name for a module note: filename, heading and wikilink all use it, so
    the link can never disagree with the file it points at."""
    return ("%s outline" % module).replace("/", "-")


def code_note_text(module: str, files, area: str, project: str) -> str:
    symbols_total = sum(len(item["symbols"]) for item in files)
    blocks = []
    for item in files:
        blocks.append("### `%s`" % item["rel"])
        blocks.append("")
        blocks.append("_%d lines, %d bytes_" % (item["lines"], item["bytes"]))
        blocks.append("")
        if item["symbols"]:
            blocks.append("| Kind | Name | Line | Declaration |")
            blocks.append("|---|---|---|---|")
            for symbol in item["symbols"]:
                blocks.append("| %s | `%s` | %d | `%s` |" % (
                    symbol["kind"], symbol["name"], symbol["line"],
                    symbol["signature"].replace("|", "\\|")))
            blocks.append("")
        else:
            blocks.append("_No declarations matched (data, styles or glue file)._")
            blocks.append("")
    return "\n".join([
        fm_block("resource", "active", area, ["reference", "code-outline"], "medium",
                 {"source": '"%s"' % module, "confidence": "medium"}),
        "# %s" % code_label(module),
        "",
        "%d files, %d declarations, extracted from the source on %s by `vault-forge ingest`." % (
            len(files), symbols_total, util.TODAY),
        "",
        *blocks,
        "## Related",
        "",
        "- [[%s]]" % project,
        "- [[Code Outline]]",
    ])


def collect_docs(repo: Path, cfg: dict, ev: dict):
    docs = []
    for path in sorted((repo / "docs").rglob("*.md")) if (repo / "docs").is_dir() else []:
        rel = path.relative_to(repo)
        excluded = set(cfg["scan"]["exclude"]) | set(DOTNET_EXCLUDE)
        if any(part in excluded or part.startswith(".") for part in rel.parts):
            continue
        docs.append((path, str(rel)))
    for path in sorted(repo.glob("*.md")):
        if path.name.lower() in ("readme.md", "license.md", "changelog.md"):
            continue
        docs.append((path, path.name))
    return docs


def collect_code(repo: Path, cfg: dict):
    modules = {}
    for path in sorted(repo.rglob("*")):
        if not path.is_file() or path.suffix not in LANG_BY_EXT:
            continue
        rel = path.relative_to(repo)
        excluded = set(cfg["scan"]["exclude"]) | set(DOTNET_EXCLUDE)
        if any(part in excluded or part.startswith(".") for part in rel.parts):
            continue
        if str(rel).startswith((cfg["vault_dir"], ".vault-forge")):
            continue
        if path.name.endswith(GENERATED_SUFFIXES):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_FILE_BYTES:
            continue
        modules.setdefault(module_key(rel, repo), []).append(path)
    return modules


def ingest(repo: Path, cfg: dict, args) -> int:
    vault = util.vault_path(repo, cfg)
    if not vault.exists():
        util.die("no vault at %s; run init first" % vault)
    project = cfg["project"]
    area = (cfg.get("areas") or ["Architecture"])[0]
    force = getattr(args, "force", False)

    from .scan import collect  # avoid a circular import at module load
    ev = collect(repo, cfg)

    # 1. documents
    doc_written, doc_kept = [], []
    doc_paths = collect_docs(repo, cfg, ev)
    for path, rel in doc_paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        title = doc_title(path, text)
        if title[0].isdigit() or re.match(r"^(adr)\b", title, re.I):
            name = title                      # the document numbers itself
        else:
            number = re.match(r"^(\d+)[-_ ]", path.name)
            name = ("%s %s" % (number.group(1), title) if number else title)
        name = name.replace("/", "-")
        destination = vault / DOC_DIR / ("%s.md" % name[:90])
        if destination.exists() and not force:
            doc_kept.append(name)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(doc_note_text(path, rel, text, project, area).rstrip() + "\n")
        doc_written.append(name)

    # 2. code outlines
    code_written, code_kept = [], []
    modules = collect_code(repo, cfg)
    for module, paths in sorted(modules.items()):
        items = []
        for path in paths[:MAX_FILES_PER_MODULE]:
            text = path.read_text(encoding="utf-8", errors="replace")
            items.append({
                "rel": str(path.relative_to(repo)),
                "lines": len(text.splitlines()),
                "bytes": len(text.encode("utf-8")),
                "symbols": extract_symbols(text, LANG_BY_EXT[path.suffix]),
            })
        if not items:
            continue
        # one label for the filename, the heading and every wikilink: they cannot disagree
        label = code_label(module)
        destination = vault / CODE_DIR / ("%s.md" % label[:90])
        if destination.exists() and not force:
            code_kept.append(label)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(code_note_text(module, items, area, project).rstrip() + "\n")
        code_written.append(label)

    # 3. the two maps, and wire them into the project note so nothing is orphaned
    docs_moc = vault / DOCS_MOC
    docs_moc.parent.mkdir(parents=True, exist_ok=True)
    docs_moc.write_text("\n".join([
        fm_block("moc", "active", area, ["moc", "reference"], "high"),
        "# Repo Docs",
        "",
        "Every document in the repository, ingested with its own section headings and source line"
        " ranges. Regenerate with `./.vault-forge/vault-forge ingest`.",
        "",
        "## Documents",
        "",
        *["- [[%s]]" % doc for doc in sorted(doc_written + doc_kept)],
        "",
        "## Related",
        "",
        "- [[%s]]" % project,
        "- [[Code Outline]]",
    ]).rstrip() + "\n")

    code_moc = vault / CODE_MOC
    code_moc.write_text("\n".join([
        fm_block("moc", "active", area, ["moc", "reference", "code-outline"], "high"),
        "# Code Outline",
        "",
        "One note per module, listing the declarations in that module with `file:line`. This is the"
        " map an agent reads before it greps.",
        "",
        "## Modules",
        "",
        *["- [[%s]]" % label for label in sorted(code_written + code_kept)],
        "",
        "## Related",
        "",
        "- [[%s]]" % project,
        "- [[Repo Docs]]",
    ]).rstrip() + "\n")

    linked = ensure_links(vault / "01-Projects" / ("%s.md" % project), ["Repo Docs", "Code Outline"])

    info("ingest: %s" % repo)
    info("  documents: %d written, %d kept" % (len(doc_written), len(doc_kept)))
    info("  modules:   %d outline notes (%d written, %d kept)" % (
        len(code_written) + len(code_kept), len(code_written), len(code_kept)))
    info("  maps:      [[Repo Docs]], [[Code Outline]]%s" % (
        " (project note linked)" if linked else ""))
    for name in doc_written[:40]:
        info("    + %s/%s.md" % (DOC_DIR, name))
    for name in code_written[:40]:
        info("    + %s/%s.md" % (CODE_DIR, label))
    return 0


def ensure_links(note_path: Path, links) -> bool:
    """Make sure a generated note references the given notes, so nothing is orphaned."""
    if not note_path.exists():
        return False
    text = note_path.read_text(encoding="utf-8")
    missing = [link for link in links if "[[%s]]" % link not in text]
    if not missing:
        return False
    additions = "\n".join("- [[%s]]" % link for link in missing)
    if "\n## Related" in text:
        text = text.rstrip() + "\n" + additions + "\n"
    else:
        text = text.rstrip() + "\n\n## Related\n\n" + additions + "\n"
    note_path.write_text(text)
    return True
