"""Install or inspect the local Obsidian add-on inside the vault."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from . import util
from .util import info, warn

REQUIRED = ("manifest.json", "main.js")
OPTIONAL = ("styles.css",)
RELEASE_ASSETS = ("manifest.json", "main.js", "styles.css")


def fetch_release(spec: str, dest: Path) -> str:
    """Download a release's install assets into dest. spec is owner/repo or owner/repo@tag.

    Uses the gh CLI when it is installed (which also covers private repos), and falls back to the
    public release API over plain HTTP so no tooling is required for a public repo.
    Returns which transport actually delivered the files.
    """
    owner_repo, _, tag = spec.partition("@")
    owner_repo = owner_repo.strip()
    if owner_repo.count("/") != 1:
        util.die("--from-github wants owner/repo or owner/repo@tag, got %r" % spec)
    dest.mkdir(parents=True, exist_ok=True)
    errors = []

    if shutil.which("gh"):
        args = ["gh", "release", "download"]
        if tag:
            args.append(tag)
        args += ["--repo", owner_repo, "--dir", str(dest), "--clobber"]
        for asset in RELEASE_ASSETS:
            args += ["--pattern", asset]
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0 and (dest / "manifest.json").exists():
            return "gh release download"
        errors.append("gh: %s" % result.stderr.decode("utf-8", "replace").strip()[:200])

    api = "https://api.github.com/repos/%s/releases/%s" % (
        owner_repo, ("tags/" + tag) if tag else "latest")
    try:
        request = urllib.request.Request(api, headers={"User-Agent": "vault-forge"})
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        wanted = {asset["name"]: asset["browser_download_url"]
                  for asset in payload.get("assets", [])}
        if "manifest.json" not in wanted:
            util.die("%s has no manifest.json asset on its latest release; nothing to install"
                     % owner_repo)
        for name in RELEASE_ASSETS:
            if name not in wanted:
                warn("release has no %s asset" % name)
                continue
            request = urllib.request.Request(wanted[name], headers={"User-Agent": "vault-forge"})
            with urllib.request.urlopen(request, timeout=30) as response:
                (dest / name).write_bytes(response.read())
        return "public release API"
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        errors.append("http: %s" % exc)
    util.die("could not fetch a release for %s: %s" % (owner_repo, "; ".join(errors)))
    return ""  # unreachable



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
    from_github = (getattr(args, "from_github", "") or "").strip()
    if from_github and getattr(args, "source", ""):
        util.die("pass either --source or --from-github, not both")
    if from_github:
        source = Path(tempfile.mkdtemp(prefix="vault-forge-release-"))
        transport = fetch_release(from_github, source)
        info("fetched %s via %s" % (from_github, transport))
        cfg.setdefault("plugin", {})["release"] = from_github
    elif getattr(args, "source", ""):
        source = Path(args.source).expanduser()
    else:
        source = default_source(cfg, repo)
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
