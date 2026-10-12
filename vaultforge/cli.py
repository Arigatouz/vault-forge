"""Command line entry point."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import indexer, ingest as ingest_mod, plugin, scaffold, util, vault as vault_mod
from . import validate as validate_mod
from . import scan as scan_mod
from .util import info


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vault-forge",
        description="Generate and maintain a project Obsidian vault inside a repository.",
    )
    parser.add_argument("--repo", default="", help="repository root (default: nearest .vault-forge or git root)")
    parser.add_argument("--version", action="version", version="vault-forge %s" % util.TOOL_VERSION)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("init", help="create the vault skeleton and vendor this tool into the repo")
    p.add_argument("--name", default="", help="project name (default: package.json name or folder name)")
    p.add_argument("--dir", default="", help="vault folder inside the repo (default: docs-vault)")
    p.add_argument("--areas", default="", help="comma separated area names")
    p.add_argument("--tags", default="", help="comma separated domain tags")
    p.add_argument("--force", action="store_true", help="re-render templates over existing files")

    p = sub.add_parser("scan", help="read the repository and seed notes from what it finds")
    p.add_argument("--force", action="store_true", help="overwrite seeded notes")

    p = sub.add_parser("ingest", help="read repository documents and source code into real notes")
    p.add_argument("--force", action="store_true", help="overwrite previously ingested notes")

    sub.add_parser("index", help="rebuild index/ for fast agent search")

    p = sub.add_parser("search", help="search the index")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--tag", default="")
    p.add_argument("--kind", default="", help="frontmatter type filter (note, decision, project, ...)")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("validate", help="the gate: frontmatter, links, orphans, canvases, bases")
    p.add_argument("--strict", action="store_true", help="treat orphans as errors")
    p.add_argument("--quiet", action="store_true")

    p = sub.add_parser("plugin", help="install or inspect the local Obsidian add-on")
    plugin_sub = p.add_subparsers(dest="plugin_command")
    install = plugin_sub.add_parser("install")
    install.add_argument("--source", default="", help="path to a built add-on directory")
    install.add_argument("--from-github", default="",
                         help="owner/repo or owner/repo@tag, e.g. Arigatouz/agent-dispatch")
    install.add_argument("--id", default="")
    plugin_sub.add_parser("status")

    p = sub.add_parser("build", help="init if needed, then scan, ingest, index and validate")
    p.add_argument("--name", default="")
    p.add_argument("--dir", default="")
    p.add_argument("--areas", default="")
    p.add_argument("--tags", default="")
    p.add_argument("--force", action="store_true")
    p.add_argument("--skip-ingest", action="store_true",
                   help="metadata only: do not read the repository documents and source")

    sub.add_parser("status", help="what this repo has right now")
    return parser


def resolve_repo(args) -> Path:
    if getattr(args, "repo", ""):
        repo = Path(args.repo).expanduser().resolve()
    else:
        repo = util.find_repo()
    if not repo.exists():
        util.die("no such directory: %s" % repo)
    return repo


def cmd_status(repo: Path, cfg: dict) -> int:
    vault = util.vault_path(repo, cfg)
    info("repo:      %s" % repo)
    info("tool:      %s" % (repo / ".vault-forge" / "vault-forge"))
    info("vault:     %s%s" % (vault, "" if vault.exists() else "  (missing: run init)"))
    info("project:   %s" % cfg["project"])
    info("areas:     %s" % (", ".join(cfg.get("areas") or []) or "(not derived yet)"))
    info("tags:      %s" % (", ".join(cfg.get("domain_tags") or []) or "(none yet)"))
    if vault.exists():
        notes = vault_mod.load_vault(vault)
        info("notes:     %d" % len(notes))
        index = vault / "index" / "vault-index.json"
        info("index:     %s" % ("built" if index.exists() else "missing (run index)"))
    info("commit index: %s" % cfg.get("commit_index", True))
    info("")
    return plugin.status(repo, cfg)


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    repo = resolve_repo(args)

    if args.command == "init":
        return scaffold.init(repo, args)
    if args.command == "build":
        cfg = util.load_config(repo)
        if not (util.vault_path(repo, cfg) / "README.md").exists():
            scaffold.init(repo, args)
        cfg = util.load_config(repo)
        scan_mod.scan(repo, cfg, args)
        if not getattr(args, "skip_ingest", False):
            ingest_mod.ingest(repo, cfg, args)
        indexer.build(repo, cfg)
        return validate_mod.run(repo, cfg, strict=False, quiet=False)

    cfg = util.load_config(repo)
    if not (repo / ".vault-forge" / "forge.json").exists() and args.command != "status":
        util.die("no .vault-forge/forge.json here; is %s the repository root? run init first" % repo)

    if args.command == "scan":
        return scan_mod.scan(repo, cfg, args)
    if args.command == "ingest":
        return ingest_mod.ingest(repo, cfg, args)
    if args.command == "index":
        return indexer.build(repo, cfg)
    if args.command == "search":
        return indexer.search(repo, cfg, args.query, limit=args.limit, tag=args.tag,
                              kind=args.kind, as_json=args.json)
    if args.command == "validate":
        return validate_mod.run(repo, cfg, strict=args.strict, quiet=args.quiet)
    if args.command == "plugin":
        if args.plugin_command == "install":
            return plugin.install(repo, cfg, args)
        if args.plugin_command == "status":
            return plugin.status(repo, cfg)
        parser.parse_args(["plugin", "--help"])
        return 2
    if args.command == "status":
        return cmd_status(repo, cfg)
    parser.print_help()
    return 2
