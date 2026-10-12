"""The gate: frontmatter, wikilinks, orphans, canvases, bases, index freshness."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import util
from .util import info
from .vault import (
    DATE_OK, REQUIRED_KEYS, STATUS_VOCAB, TYPE_VOCAB, area_name, is_template, load_vault,
    resolution_index, resolve,
)

BASE_FORMULA_ORDER = re.compile(r"^\s*-\s*(formula\.\w+)\s*$", re.M)


def run(repo: Path, cfg: dict, strict: bool = False, quiet: bool = False) -> int:
    vault = util.vault_path(repo, cfg)
    if not vault.exists():
        util.die("no vault at %s; run init first" % vault)
    notes = load_vault(vault, include_templates=True)
    table = resolution_index(notes)
    errors, warnings = [], []
    checks = []

    # 1. frontmatter
    fm_bad = 0
    for note in notes:
        if is_template(note) or note.path.endswith((".canvas", ".base")):
            continue
        if note.fm_error:
            errors.append("%s: %s" % (note.path, note.fm_error))
            fm_bad += 1
            continue
        for key in REQUIRED_KEYS:
            if key not in note.frontmatter or note.frontmatter[key] in ("", None):
                errors.append("%s: missing frontmatter key %r" % (note.path, key))
                fm_bad += 1
        type_value = str(note.frontmatter.get("type", ""))
        status_value = str(note.frontmatter.get("status", ""))
        if type_value and type_value not in TYPE_VOCAB:
            errors.append("%s: type %r outside the vocabulary" % (note.path, type_value))
            fm_bad += 1
        if status_value and status_value not in STATUS_VOCAB:
            errors.append("%s: status %r outside the vocabulary" % (note.path, status_value))
            fm_bad += 1
        for key in ("created", "updated"):
            value = str(note.frontmatter.get(key, ""))
            if value and not DATE_OK.match(value):
                errors.append("%s: %s %r is not YYYY-MM-DD" % (note.path, key, value))
                fm_bad += 1
    checks.append(("frontmatter", len([n for n in notes if not n.path.endswith((".canvas", ".base"))]) - fm_bad, fm_bad))

    # 2. wikilinks resolve
    unresolved = 0
    for note in notes:
        for link in note.links + note.embeds:
            target = link["target"]
            if target.startswith(("http://", "https://")):
                continue
            if not resolve(target, table):
                unresolved += 1
                errors.append("%s:%d: unresolved link [[%s]]" % (note.path, link["line"], target))
    checks.append(("wikilinks", sum(len(n.links) + len(n.embeds) for n in notes) - unresolved, unresolved))

    # 3. orphans (no inbound links, canvases and bases count as sources)
    inbound = {}
    for note in notes:
        for link in note.links + note.embeds:
            for resolved in resolve(link["target"], table):
                inbound[resolved] = inbound.get(resolved, 0) + 1
    for note in notes:
        if is_template(note) or note.path.endswith((".canvas", ".base")):
            continue
        if note.path.startswith("index/"):
            continue
        if inbound.get(note.path, 0) == 0:
            message = "%s: no inbound links (orphan)" % note.path
            (errors if strict else warnings).append(message)
    checks.append(("orphans", len([n for n in notes if inbound.get(n.path, 0) > 0]),
                   len([w for w in warnings if w.endswith("(orphan)")])))

    # 4. canvases
    canvas_bad = 0
    for path in sorted(vault.rglob("*.canvas")):
        rel = str(path.relative_to(vault))
        try:
            payload = json.loads(path.read_text())
        except ValueError as exc:
            errors.append("%s: not valid JSON (%s)" % (rel, exc))
            canvas_bad += 1
            continue
        ids = [node.get("id") for node in payload.get("nodes", [])]
        if len(ids) != len(set(ids)):
            errors.append("%s: duplicate node ids" % rel)
            canvas_bad += 1
        for edge in payload.get("edges", []):
            for key in ("fromNode", "toNode"):
                if edge.get(key) not in ids:
                    errors.append("%s: edge %s -> unknown node %r" % (rel, edge.get("id"), edge.get(key)))
                    canvas_bad += 1
        for node in payload.get("nodes", []):
            if node.get("type") != "file":
                continue
            target = str(node.get("file", ""))
            stem = Path(target).stem
            if not (vault / target).exists() and stem not in table:
                errors.append("%s: file node points at a missing note %r" % (rel, target))
                canvas_bad += 1
    checks.append(("canvases", len(list(vault.rglob("*.canvas"))) - canvas_bad, canvas_bad))

    # 5. bases
    base_bad = 0
    for path in sorted(vault.rglob("*.base")):
        rel = str(path.relative_to(vault))
        text = path.read_text(encoding="utf-8", errors="replace")
        for section in ("filters:", "views:"):
            if section not in text:
                errors.append("%s: no %s block" % (rel, section))
                base_bad += 1
        formulas = set(re.findall(r"^\s{2}(\w+):", text.split("formulas:")[1].split("views:")[0], re.M)) \
            if "formulas:" in text and "views:" in text else set()
        for name in BASE_FORMULA_ORDER.findall(text):
            if formulas and name.split(".", 1)[1] not in formulas:
                errors.append("%s: order references %s with no matching formula" % (rel, name))
                base_bad += 1
    checks.append(("bases", len(list(vault.rglob("*.base"))) - base_bad, base_bad))

    # 6. index freshness
    index_file = vault / "index" / "vault-index.json"
    if not index_file.exists():
        warnings.append("index/vault-index.json missing; run: ./.vault-forge/vault-forge index")
        index_state = "missing"
    else:
        newest = max([n.abs.stat().st_mtime for n in notes] or [0])
        if index_file.stat().st_mtime < newest:
            warnings.append("index is older than the newest note; run: ./.vault-forge/vault-forge index")
            index_state = "stale"
        else:
            index_state = "current"
    checks.append(("index", 1 if index_state == "current" else 0,
                   0 if index_state == "current" else 1))

    # report
    if not quiet:
        info("vault: %s" % vault)
        info("%-13s %8s %8s" % ("check", "ok", "issues"))
        for name, ok, bad in checks:
            info("%-13s %8d %8d" % (name, ok, bad))
        info("")
        for warning in warnings:
            info("warning: %s" % warning)
    for error in errors[:60]:
        info("error:   %s" % error)
    if len(errors) > 60:
        info("error:   ... %d more" % (len(errors) - 60))
    if errors or not quiet:
        info("")
    if errors:
        info("FAIL: %d error(s), %d warning(s)" % (len(errors), len(warnings)))
        return 1
    info("PASS: 0 errors, %d warning(s)" % len(warnings))
    return 0
