"""Scan the repository and seed the vault with evidence-based notes."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import util
from .util import info, warn

# Build output and caches that never belong in a vault note. Applied on top of the configured list.
DOTNET_EXCLUDE = {"bin", "obj", ".vs", "TestResults", "artifacts", "packages"}

SOURCE_EXT = {
    ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript",
    ".rs": "Rust", ".py": "Python", ".go": "Go", ".java": "Java", ".cs": "C#",
    ".astro": "Astro", ".vue": "Vue", ".svelte": "Svelte", ".css": "CSS", ".scss": "SCSS",
    ".html": "HTML", ".md": "Markdown", ".json": "JSON", ".toml": "TOML", ".yml": "YAML",
    ".sh": "Shell", ".sql": "SQL", ".c": "C", ".cpp": "C++", ".rb": "Ruby", ".php": "PHP",
}

FRAMEWORKS = [
    ("@angular/core", "Angular"), ("react", "React"), ("vue", "Vue"), ("svelte", "Svelte"),
    ("next", "Next.js"), ("nuxt", "Nuxt"), ("@tauri-apps/api", "Tauri"), ("electron", "Electron"),
    ("express", "Express"), ("fastify", "Fastify"), ("hono", "Hono"), ("vite", "Vite"),
    ("tailwindcss", "Tailwind CSS"), ("typescript", "TypeScript"), ("rxjs", "RxJS"),
    ("@biomejs/biome", "Biome"), ("eslint", "ESLint"), ("vitest", "Vitest"),
    ("jest", "Jest"), ("playwright", "Playwright"), ("bun-types", "Bun"),
]

AREA_TITLES = {
    "src": "Frontend", "app": "Frontend", "web": "Frontend", "ui": "Frontend",
    "src-tauri": "Desktop Shell", "tauri": "Desktop Shell", "desktop": "Desktop Shell",
    "orchestrator": "Orchestrator", "server": "Backend", "api": "Backend", "backend": "Backend",
    "packages": "Packages", "libs": "Libraries", "crates": "Rust Crates",
}


def _excluded(rel: Path, cfg, extra=None) -> bool:
    parts = set(rel.parts)
    if parts & set(cfg["scan"]["exclude"]) or parts & set(extra or ()) or ".vault-forge" in parts:
        return True
    if any(p.startswith(".") for p in rel.parts):
        return True
    vault_dir = str(cfg.get("vault_dir", "docs-vault")).strip("/")
    flat = str(rel).replace("\\", "/")
    return flat == vault_dir or flat.startswith(vault_dir + "/")


def collect(repo: Path, cfg: dict) -> dict:
    ev = {"repo": str(repo), "sources": []}
    pkg_path = repo / "package.json"
    pkg = util.read_json(pkg_path, {}) if pkg_path.exists() else {}
    if pkg:
        ev["sources"].append("package.json")
    ev["pkg"] = pkg
    ev["name"] = pkg.get("name") or repo.name
    ev["version"] = pkg.get("version", "")
    ev["scripts"] = pkg.get("scripts", {}) if isinstance(pkg.get("scripts"), dict) else {}
    deps = {}
    for key in ("dependencies", "devDependencies"):
        block = pkg.get(key)
        if isinstance(block, dict):
            deps.update(block)
    ev["deps"] = deps
    ev["frameworks"] = sorted({label for name, label in FRAMEWORKS if name in deps}, key=str.lower)
    if (repo / "src-tauri" / "Cargo.toml").exists() or list(repo.glob("Cargo.toml")):
        ev["frameworks"].append("Rust")
        ev["sources"].append("Cargo.toml")
    ev["dotnet_target"] = ""
    ev["dotnet_projects"] = []
    solutions = list(repo.glob("*.sln"))
    projects = sorted(
        {p for depth in ("*/*.csproj", "*/*/*.csproj", "*/*/*/*.csproj") for p in repo.glob(depth)}
    )
    if solutions or projects:
        ev["frameworks"].append("C# / .NET")
        ev["sources"].append(solutions[0].name if solutions else "a .csproj file")
        ev["dotnet_projects"] = [p.stem for p in projects][:12]
        for candidate in projects[:6]:
            match = re.search(r"<TargetFramework>([^<]+)</TargetFramework>", candidate.read_text(
                encoding="utf-8", errors="replace"))
            if match:
                ev["dotnet_target"] = match.group(1).strip()
                break
    if (repo / "pyproject.toml").exists():
        ev["sources"].append("pyproject.toml")

    # .NET build output stays out of the notes: bin/ and obj/ are generated, not source.
    extra = DOTNET_EXCLUDE if "C# / .NET" in ev["frameworks"] else set()
    ev["dotnet_excluded"] = sorted(extra) if extra else []

    readme = repo / "README.md"
    ev["readme_heading"] = ""
    ev["readme_summary"] = ""
    if readme.exists():
        ev["sources"].append("README.md")
        lines = readme.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines:
            if line.startswith("# "):
                ev["readme_heading"] = line[2:].strip()
                break
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith(("#", "!", "[", "|", "<")):
                ev["readme_summary"] = re.sub(r"\s+", " ", stripped)[:400]
                break

    ev["git"] = {}
    branch = util.git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch:
        ev["git"]["branch"] = branch
        ev["git"]["head"] = util.git(repo, "rev-parse", "--short", "HEAD").strip()
        log = util.git(repo, "log", "--pretty=format:%h %ad %s", "--date=short",
                       "-n", str(cfg["scan"]["git_log"]))
        ev["git"]["log"] = [line for line in log.splitlines() if line.strip()]
        shortlog = util.git(repo, "shortlog", "-sn", "HEAD")
        ev["git"]["contributors"] = [line.strip() for line in shortlog.splitlines()[:8]]
        ev["sources"].append("git history")

    dirs, ext_counts, files = [], {}, []
    for path in sorted(repo.rglob("*")):
        try:
            rel = path.relative_to(repo)
        except ValueError:
            continue
        if _excluded(rel, cfg, extra):
            continue
        if path.is_dir():
            if len(rel.parts) <= 2:
                dirs.append(str(rel))
            continue
        ext_counts[path.suffix] = ext_counts.get(path.suffix, 0) + 1
        if path.suffix in SOURCE_EXT and path.suffix != ".json":
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            files.append((size, str(rel)))
    files.sort(reverse=True)
    ev["dirs"] = dirs
    ev["ext_counts"] = dict(sorted(ext_counts.items(), key=lambda kv: -kv[1]))
    ev["top_files"] = files[: cfg["scan"]["max_files"]]
    ev["languages"] = sorted(
        {SOURCE_EXT.get(Path(name).suffix, "") for _s, name in ev["top_files"]} - {""}
    )
    ev["docs"] = [str(p.relative_to(repo)) for p in sorted((repo / "docs").rglob("*"))
                  if p.is_file()] if (repo / "docs").is_dir() else []
    adr = [n for n in ev["docs"] if re.search(r"adr|decision", n, re.I)]
    ev["adr_candidates"] = adr
    if ev["docs"]:
        ev["sources"].append("docs/")
    for candidate in ("CONTRIBUTING.md", "biome.json", "angular.json", ".editorconfig",
                      "GEMINI.md", "CLAUDE.md", "AGENTS.md", "tsconfig.json"):
        if (repo / candidate).exists():
            ev.setdefault("config_files", []).append(candidate)
    return ev


def derive_areas(ev: dict) -> list:
    areas = ["Architecture"]
    for folder in ev["dirs"]:
        if "/" in folder:
            continue
        title = AREA_TITLES.get(folder)
        if title and title not in areas:
            areas.append(title)
    return areas


def fm_block(type_, status, area=None, tags=(), priority="medium", extra=None, date=None) -> str:
    date = date or util.TODAY
    lines = ["---", "type: %s" % type_, "status: %s" % status]
    if area:
        lines.append('area: "[[%s]]"' % area)
    tag_list = ", ".join(tags)
    lines.append("tags: [%s]" % tag_list if tag_list else "tags: []")
    lines += ["created: %s" % date, "updated: %s" % date, "priority: %s" % priority]
    for key, value in (extra or {}).items():
        lines.append("%s: %s" % (key, value))
    lines.append("---")
    return "\n".join(lines)


class Writer:
    def __init__(self, vault: Path, force: bool):
        self.vault = vault
        self.force = force
        self.written = []
        self.kept = []

    def note(self, rel: str, text: str) -> None:
        dest = self.vault / rel
        if dest.exists() and not self.force:
            self.kept.append(rel)
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text.rstrip() + "\n", encoding="utf-8")
        self.written.append(rel)

    def asset(self, rel: str, payload) -> None:
        dest = self.vault / rel
        if dest.exists() and not self.force:
            self.kept.append(rel)
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        self.written.append(rel)


def seed(repo: Path, cfg: dict, ev: dict, force: bool = False):
    vault = util.vault_path(repo, cfg)
    writer = Writer(vault, force)
    areas = cfg.get("areas") or derive_areas(ev)
    cfg["areas"] = areas
    project = cfg["project"]
    tags = cfg.get("domain_tags") or [util.slug(t.split(" / ")[0]) for t in ev["frameworks"]][:6] or ["codebase"]
    if not cfg.get("domain_tags"):
        cfg["domain_tags"] = tags
    primary_area = areas[0]
    source_line = "Generated by `vault-forge` on %s from %s." % (
        util.TODAY, ", ".join(ev["sources"]) or "the repository tree")

    # 01-Projects/<project>.md
    stack_lines = []
    for label in ev["frameworks"]:
        stack_lines.append("- %s" % label)
    for language in ev["languages"]:
        if language not in ev["frameworks"]:
            stack_lines.append("- %s" % language)
    if ev.get("dotnet_target"):
        stack_lines.append("- C# / .NET, target framework `%s`" % ev["dotnet_target"])
    if ev.get("dotnet_projects"):
        stack_lines.append("- Projects: %s" % ", ".join("`%s`" % n for n in ev["dotnet_projects"]))
    if not stack_lines:
        stack_lines.append("- (no package manifest found; stack not detected)")
    script_rows = ["| Command | What it runs |", "|---|---|"]
    for name, command in list(ev["scripts"].items())[:15]:
        script_rows.append("| `%s` | `%s` |" % (name, str(command)[:90].replace("|", "\\|")))
    if len(script_rows) == 2:
        script_rows.append("| (none) | no scripts declared |")
    history = ["- %s" % line for line in ev["git"].get("log", [])[:20]] or ["- no git history found"]
    project_note = "\n".join([
        fm_block("project", "active", primary_area, ["project"], "high",
                 {"next_action": '""', "due": '""', "repo": '"%s"' % repo}),
        "# %s" % (ev["readme_heading"] or project),
        "",
        ev["readme_summary"] or "One line on what this repo is and who it is for.",
        "",
        "## Stack",
        "",
        *stack_lines,
        "",
        "## Commands",
        "",
        *script_rows,
        "",
        "## Layout",
        "",
        "See [[Codebase Map]] for the generated tree and the largest source files.",
        "",
        "## History",
        "",
        *history,
        "",
        "## Notes",
        "",
        source_line,
        "",
        "## Related",
        "",
        *["- [[%s]]" % a for a in areas],
        "- [[Codebase Map]]",
        "- [[Repo Conventions]]",
    ])
    writer.note("01-Projects/%s.md" % project, project_note)

    # 02-Areas/<Area>/<Area>.md
    for area in areas:
        others = [a for a in areas if a != area]
        body = "\n".join([
            fm_block("area", "active", None, ["area", "moc"], "medium"),
            "# %s" % area,
            "",
            "Long-lived responsibility for this project. Not a task list: things that are never done.",
            "",
            "## Contents",
            "",
            "- [[%s]]" % project,
            *["- [[%s]]" % name for name in ([a for a in others][:3])],
            "",
            "## Related",
            "",
            "- [[Home]]",
            "- [[%s]]" % project,
        ])
        writer.note("02-Areas/%s/%s.md" % (area, area), body)

    # 03-Resources/Codebase Map.md
    tree_lines = ["```text", repo.name + "/"]
    for folder in ev["dirs"]:
        depth = folder.count("/")
        if depth > 1:
            continue
        tree_lines.append("  " * (depth + 1) + folder.split("/")[-1] + "/")
    tree_lines.append("```")
    file_rows = ["| File | Bytes |", "|---|---|"]
    for size, name in ev["top_files"][:25]:
        file_rows.append("| `%s` | %d |" % (name, size))
    ext_rows = ["| Extension | Files |", "|---|---|"]
    for ext, count in list(ev["ext_counts"].items())[:12]:
        ext_rows.append("| `%s` | %d |" % (ext or "(none)", count))
    map_note = "\n".join([
        fm_block("resource", "active", primary_area, ["reference", "codebase"], "high",
                 {"source": '"repository tree"', "confidence": "medium"}),
        "# Codebase Map",
        "",
        "Where things live in `%s`. Generated from the file tree, so it is a starting point, not a" % repo,
        "substitute for reading the code.",
        "",
        "## Top level",
        "",
        *tree_lines,
        "",
        "## Largest source files",
        "",
        *file_rows,
        "",
        "## File mix",
        "",
        *ext_rows,
        "",
        "## Docs in the repo",
        "",
        *(["- `%s`" % d for d in ev["docs"][:20]] or ["- no `docs/` folder in this repo"]),
        "",
        "## Related",
        "",
        "- [[%s]]" % project,
        "- [[Repo Conventions]]",
        "",
        source_line,
    ])
    writer.note("03-Resources/Codebase Map.md", map_note)

    # 03-Resources/Repo Conventions.md
    config_lines = ["- `%s`" % c for c in ev.get("config_files", [])] or ["- none detected"]
    adr_lines = ["- `%s`" % a for a in ev["adr_candidates"][:15]] or ["- none found under `docs/`"]
    test_cmd = ev["scripts"].get("test") or ev["scripts"].get("verify") or "(not declared)"
    conv_note = "\n".join([
        fm_block("resource", "active", primary_area, ["reference", "tooling"], "medium",
                 {"source": '"repo configuration"', "confidence": "medium"}),
        "# Repo Conventions",
        "",
        "How this repository builds, tests and formats. Taken from the files below, not from memory.",
        "",
        "## Config files found",
        "",
        *config_lines,
        "",
        "## Test and verify",
        "",
        "- test: `%s`" % test_cmd,
        "- verify: `%s`" % (ev["scripts"].get("verify") or "(not declared)"),
        "",
        "## Decision records in the repo",
        "",
        *adr_lines,
        "",
        "## Related",
        "",
        "- [[%s]]" % project,
        "- [[Codebase Map]]",
        "",
        source_line,
    ])
    writer.note("03-Resources/Repo Conventions.md", conv_note)

    # 00-Inbox/Inbox.md
    inbox = "\n".join([
        fm_block("moc", "inbox", None, ["inbox", "moc"], "low"),
        "# Inbox",
        "",
        "Unfiled captures land here first. Remove the `#inbox` tag when a capture is filed.",
        "",
        "## Captures",
        "",
        "-",
        "",
        "## Related",
        "",
        "- [[Home]]",
    ])
    writer.note("00-Inbox/Inbox.md", inbox)

    # 07-Daily/<today>.md
    daily = "\n".join([
        fm_block("daily", "active", None, ["daily"], "low"),
        "# %s" % util.TODAY,
        "",
        "Work touched today. Link the notes, do not restate them.",
        "",
        "- [[%s]]" % project,
        *["- [[%s]]" % a for a in areas[:3]],
        "",
        "## Related",
        "",
        "- [[Home]]",
    ])
    writer.note("07-Daily/%s.md" % util.TODAY, daily)

    # 06-Canvases/Vault Overview.canvas
    nodes = [
        {"id": "home", "type": "file", "file": "Home.md", "x": -400, "y": 0, "width": 420, "height": 200},
        {"id": "dashboard", "type": "file", "file": "05-Dashboards/Dashboard.md",
         "x": 120, "y": 0, "width": 420, "height": 200},
        {"id": "project", "type": "file", "file": "01-Projects/%s.md" % project,
         "x": -400, "y": 300, "width": 420, "height": 200},
        {"id": "map", "type": "file", "file": "03-Resources/Codebase Map.md",
         "x": 120, "y": 300, "width": 420, "height": 200},
        {"id": "conv", "type": "file", "file": "03-Resources/Repo Conventions.md",
         "x": 640, "y": 300, "width": 420, "height": 200},
        {"id": "readme", "type": "file", "file": "README.md", "x": 120, "y": 600, "width": 420, "height": 180},
    ]
    edges = [
        {"id": "e1", "fromNode": "home", "toNode": "dashboard"},
        {"id": "e2", "fromNode": "home", "toNode": "project"},
        {"id": "e3", "fromNode": "project", "toNode": "map"},
        {"id": "e4", "fromNode": "project", "toNode": "conv"},
        {"id": "e5", "fromNode": "home", "toNode": "readme"},
    ]
    x = -400
    for index, area in enumerate(areas, start=1):
        node_id = "area%d" % index
        nodes.append({"id": node_id, "type": "file", "file": "02-Areas/%s/%s.md" % (area, area),
                      "x": x, "y": 900, "width": 300, "height": 160})
        edges.append({"id": "ea%d" % index, "fromNode": "project", "toNode": node_id})
        x += 320
    writer.asset("06-Canvases/Vault Overview.canvas", {"nodes": nodes, "edges": edges})

    return writer.written, writer.kept, areas, tags


def scan(repo: Path, cfg: dict, args) -> int:
    vault = util.vault_path(repo, cfg)
    if not vault.exists():
        util.die("no vault at %s; run init first" % vault)
    ev = collect(repo, cfg)
    written, kept, areas, tags = seed(repo, cfg, ev, force=getattr(args, "force", False))
    util.save_config(repo, cfg)

    info("scanned: %s" % repo)
    info("  evidence: %s" % (", ".join(ev["sources"]) or "repository tree"))
    info("  stack:    %s" % (", ".join(ev["frameworks"]) or "not detected"))
    info("  areas:    %s" % ", ".join(areas))
    info("  tags:     %s" % ", ".join(tags))
    info("  commits:  %d read, HEAD %s" % (len(ev["git"].get("log", [])), ev["git"].get("head", "-")))
    if ev.get("dotnet_excluded"):
        info("  skipped:  %s (dotnet build output)" % ", ".join(ev["dotnet_excluded"]))
    info("  wrote:    %d notes" % len(written))
    if kept:
        info("  kept:     %d existing notes untouched (use --force to re-seed)" % len(kept))
    for name in written:
        info("    + %s" % name)
    return 0
