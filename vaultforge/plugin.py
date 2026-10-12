"""Install or inspect the local Obsidian add-on inside the vault."""
from __future__ import annotations

import json
from pathlib import Path

from . import util
from .util import info, warn

REQUIRED = ("manifest.json", "main.js")
OPTIONAL = ("styles.css",)


def default_source(cfg: dict, repo: Path):
    configured = (cfg.get("plugin") or {}).get("source") or ""
    if configured:
        return Path(configured).expanduser()
    for candidate in (
        util.tool_root().parent / "agent-dispatch",
        repo / "vendor" / "agent-dispatch",
        repo / ".vault-forge" / "vendor" / "agent-dispatch",
    ):
        if (candidate / "manifest.json").exists():
            return candidate
    return None


def plugin_dir(repo: Path, cfg: dict) -> Path:
    plugin_id = (cfg.get("plugin") or {}).get("id", "agent-dispatch")
    return util.vault_path(repo, cfg) / ".obsidian" / "plugins" / plugin_id


def install(repo: Path, cfg: dict, args) -> int:
    plugin_id = getattr(args, "id", "") or (cfg.get("plugin") or {}).get("id", "agent-dispatch")
    cfg.setdefault("plugin", {})["id"] = plugin_id
    source = Path(args.source).expanduser() if getattr(args, "source", "") else default_source(cfg, repo)
    if source is None:
        util.die("no add-on source found; pass --source /path/to/agent-dispatch or set "
                 "plugin.source in .vault-forge/forge.json")
    source = source.resolve()
    missing = [name for name in REQUIRED if not (source / name).exists()]
    if missing:
        if "main.js" in missing:
            util.die("%s has no main.js. Build it first:  cd %s && npm install && npm run build"
                     % (source, source))
        util.die("%s is missing %s" % (source, ", ".join(missing)))
    manifest = json.loads((source / "manifest.json").read_text())
    plugin_id = str(manifest.get("id") or plugin_id)
    cfg.setdefault("plugin", {})["id"] = plugin_id
    if not (source / "styles.css").exists():
        warn("%s has no styles.css; the add-on will load unstyled" % source)
    cfg.setdefault("plugin", {})["source"] = str(source)
    util.save_config(repo, cfg)

    dest = plugin_dir(repo, cfg)
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for name in REQUIRED + OPTIONAL:
        src = source / name
        if src.exists():
            (dest / name).write_bytes(src.read_bytes())
            written.append(name)

    registry = util.vault_path(repo, cfg) / ".obsidian" / "community-plugins.json"
    listed = util.read_json(registry, [])
    if not isinstance(listed, list):
        listed = []
    if manifest.get("id") not in listed:
        listed.append(manifest.get("id"))
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text(json.dumps(listed, indent=2) + "\n")
        info("enabled in community-plugins.json: %s" % manifest.get("id"))

    info("installed %s %s" % (manifest.get("id"), manifest.get("version", "")))
    info("  from: %s" % source)
    info("  to:   %s" % dest)
    info("  files: %s" % ", ".join(written))
    info("")
    info("The vault folder is inside the repository, so committing it gives every teammate the same")
    info("add-on on clone. Only per-user state stays out (see the vault .gitignore).")
    info("Loading it in the running app: Settings > Community plugins, or restart Obsidian.")
    return 0


def status(repo: Path, cfg: dict) -> int:
    dest = plugin_dir(repo, cfg)
    plugin_id = (cfg.get("plugin") or {}).get("id", "agent-dispatch")
    registry = util.vault_path(repo, cfg) / ".obsidian" / "community-plugins.json"
    listed = util.read_json(registry, [])
    info("add-on:    %s" % plugin_id)
    info("source:    %s" % ((cfg.get("plugin") or {}).get("source") or "not recorded"))
    info("installed: %s" % ("yes" if (dest / "main.js").exists() else "no"))
    if (dest / "main.js").exists():
        info("  main.js  %d bytes" % (dest / "main.js").stat().st_size)
    info("enabled:   %s" % ("yes" if plugin_id in listed else "no (%s)" % registry))
    return 0
