"""vault-forge: shared helpers (stdlib only, Python 3.9+)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

TOOL_VERSION = "0.2.0"
TODAY = date.today().isoformat()

DEFAULT_CONFIG = {
    "project": "",
    "vault_dir": "docs-vault",
    "areas": [],
    "domain_tags": [],
    "commit_index": True,
    "scan": {
        "git_log": 40,
        "max_files": 60,
        "exclude": [
            "node_modules", ".git", "dist", "build", "out", ".angular", "target",
            ".next", ".turbo", "coverage", "vendor", ".venv", "venv", "__pycache__",
        ],
    },
    "plugin": {"id": "agent-dispatch", "source": ""},
    "env_var": "PROJECT_VAULT_PATH",
}

TAG_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with", "is", "are"}


def die(msg: str, code: int = 2) -> None:
    sys.stderr.write("vault-forge: %s\n" % msg)
    sys.exit(code)


def info(msg: str) -> None:
    sys.stdout.write("%s\n" % msg)


def warn(msg: str) -> None:
    sys.stdout.write("warning: %s\n" % msg)


def find_repo(start=None) -> Path:
    """Nearest ancestor that carries .vault-forge/forge.json, else nearest git root."""
    cur = Path(start or os.getcwd()).resolve()
    chain = [cur] + list(cur.parents)
    for p in chain:
        if (p / ".vault-forge" / "forge.json").exists():
            return p
    for p in chain:
        if (p / ".git").exists():
            return p
    return cur


def tool_root() -> Path:
    """Directory holding this vendored copy of vault-forge."""
    return Path(__file__).resolve().parent.parent


def load_config(repo: Path) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    path = repo / ".vault-forge" / "forge.json"
    if path.exists():
        try:
            user = json.loads(path.read_text())
        except ValueError as exc:
            die("cannot parse %s: %s" % (path, exc))
        for key, value in user.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
    if not cfg.get("project"):
        cfg["project"] = repo.name
    return cfg


def save_config(repo: Path, cfg: dict) -> None:
    path = repo / ".vault-forge" / "forge.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n")


def vault_path(repo: Path, cfg: dict) -> Path:
    return repo / cfg["vault_dir"]


def git(repo: Path, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo)] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        )
    except OSError:
        return ""
    if out.returncode != 0:
        return ""
    return out.stdout.decode("utf-8", "replace")


def slug(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", text.strip().lower())
    return text.strip("-") or "project"


def render(text: str, values: dict) -> str:
    for key, value in values.items():
        text = text.replace("{{%s}}" % key, str(value))
    return text


def now_stamp() -> str:
    return date.today().isoformat()


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except ValueError:
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def one_line(text: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text
