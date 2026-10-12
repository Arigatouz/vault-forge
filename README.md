# vault-forge

Generate and maintain a project knowledge vault (Obsidian) **inside an application repository**, so the
knowledge travels with the code and every teammate gets the same thing on clone.

`vault-forge` is a single stdlib-only Python program. It has no dependencies, it needs no Obsidian
plugins to work, and everything it writes is plain Markdown, YAML frontmatter and JSON that diffs in a
pull request.

## Install

```bash
# run it straight from GitHub, no clone, no install
npx -y github:Arigatouz/vault-forge init --name "My App"
npx -y github:Arigatouz/vault-forge build
npx -y github:Arigatouz/vault-forge search "query"

# or clone it and call the engine directly
git clone https://github.com/Arigatouz/vault-forge.git ~/tools/vault-forge
python3 ~/tools/vault-forge/vault-forge build
```

The npx entry point is a small Node launcher (`bin/vault-forge.js`) over a stdlib-only Python engine, so
it needs Node 18+ and Python 3.9+ on the machine. Both are present on any dev box; the launcher prints
install hints and exits 2 if Python is missing. Once `init` has run, always use the vendored copy inside
the repo (`./.vault-forge/vault-forge`), because that is the version the team pinned.

## What it produces in a repo

```
<repo>/
├─ .vault-forge/            the tool, vendored, committed (forge.json holds the settings)
│  ├─ vault-forge
│  ├─ vaultforge/
│  ├─ templates/
│  └─ forge.json
└─ docs-vault/              the vault, committed, openable in Obsidian
   ├─ README.md             the conventions contract every agent and teammate follows
   ├─ Home.md               front door
   ├─ 00-Inbox … 09-Attachments        folder map (projects, areas, resources, content, dashboards,
   │                                   canvases, daily, archive, attachments)
   ├─ 05-Dashboards/        Dashboard.md plus four .base views (projects, content, resources, daily)
   ├─ 06-Canvases/          Vault Overview.canvas
   ├─ 07-Daily/             daily note for today
   ├─ Templates/            ten note templates carrying the frontmatter schema
   ├─ .obsidian/            app config, graph colour groups, snippets, theme, plugins
   └─ index/                generated search index (see below)
```

## Quick start, four steps

```bash
cd <repo>

# 1. create the vault inside the repo (also vendors the tool into .vault-forge/)
npx -y github:Arigatouz/vault-forge init --name "My App"

# 2. install the local add-on from its GitHub release
./.vault-forge/vault-forge plugin install --from-github Arigatouz/agent-dispatch

# 3. read the repository and seed the vault, then build the index and run the gate
./.vault-forge/vault-forge build

# 4. prove the add-on actually started in this vault (exit 0, or it names the two clicks)
./.vault-forge/vault-forge plugin doctor

# 5. keep the index fresh after note edits (agents search this instead of grepping)
./.vault-forge/vault-forge index
```

Steps 2 and 3 can be run in the other order; `build` is `init` (if missing) plus `scan` plus `index`
plus `validate`.

## Commands

| Command | What it does |
|---|---|
| `init` | Create the folder skeleton, Obsidian config, templates and vault README; vendor the tool into `.vault-forge/`; write `forge.json`. Never overwrites existing notes. |
| `scan` | Read `package.json`, `README.md`, `Cargo.toml`, `docs/`, the git log and the file tree, then seed the project note, area MOCs, codebase map, conventions note, inbox, daily note and canvas. Evidence-based: every claim in a seeded note names its source. |
| `index` | Write `index/vault-index.json`, `index/chunks.jsonl` (heading-level chunks with line ranges) and `index/index.md`. |
| `search "query"` | Ranked hits as `path:line` plus snippet, with how many query terms matched. `--json` for agents, `--tag` / `--kind` filters. |
| `validate` | The gate: frontmatter keys and vocabulary, wikilink resolution, orphans, canvas JSON, base YAML, index freshness. Exit code 1 on errors. `--strict` makes orphans errors. |
| `plugin install` | Install the Obsidian add-on into the vault, either `--from-github owner/repo[@tag]` (downloads the release assets, via `gh` when present else the public release API) or `--source /path/to/built-addon`. Reads the id from the add-on's own manifest and adds it to `community-plugins.json`. |
| `build` | `init` + `scan` + `ingest` + `index` + `validate` in one command (`--skip-ingest` for the metadata-only path). |
| `plugin doctor` | Exit 0 only when the add-on is installed **and** known to have started in this vault, by reading its `LOADED.txt` heartbeat. Fails with the two-click fix when community plugins are off for that vault. |
| `status` | What this repo has right now: vault path, notes, index state, add-on state. |

Global flag: `--repo <path>` (default: nearest ancestor with `.vault-forge/forge.json`, else the git root).

## The index (the RAG-like part, without a vector store)

Agents reach files faster because the vault carries a pre-built index instead of being grepped:

- `index/vault-index.json`: one record per note with title, type, status, tags, headings with line
  numbers, and outbound links.
- `index/chunks.jsonl`: heading-level chunks, each with a line range, so a hit can be cited as
  `path:line` without loading the file.
- `index/index.md`: a human catalog grouped by folder with one line per note.

`search` scores literal term hits with a boost for title, heading, path and full-phrase matches, and
reports `terms matched` (for example `3/3`) so a weak partial match is visible rather than presented as
a good one. No model, no network, no embedding endpoint: deterministic and instant.

Semantic search is deliberately not in v1. When it is added it should be a local embedding pass plus a
rerank step, not a hosted call, and the index stays the source of truth.

## Team workflow

- Commit `.vault-forge/` and `docs-vault/`. The vault is reviewable like code: a note claiming a
  behaviour change lands with the change that caused it.
- `docs-vault/.gitignore` keeps per-user state out: `.obsidian/workspace.json`, plugin `data.json`,
  caches.
- The built add-on is committed inside the vault, so a clone plus enabling the plugin is the whole
  setup. Rebuild it only when the add-on itself changes.
- Set `commit_index` to `false` in `forge.json` to keep `index/` out of git and regenerate locally.
- CI gate: `./.vault-forge/vault-forge validate` exits non-zero on a broken link, a missing frontmatter
  key or a stale index.

## Configuration (`forge.json`)

```json
{
  "project": "my-app",
  "vault_dir": "docs-vault",
  "areas": ["Architecture", "Frontend"],
  "domain_tags": ["angular", "tooling"],
  "commit_index": true,
  "scan": {"git_log": 40, "max_files": 60, "exclude": ["node_modules", ".git", "dist", "target"]},
  "plugin": {"id": "agent-dispatch", "source": "/path/to/agent-dispatch"}
}
```

Every key is optional. With no `areas`, areas are derived from the top-level source folders. With no
`domain_tags`, tags come from the detected stack. See `forge.json.example`.

## Verifying it

```bash
bash tests/selftest.sh      # 31 checks: build, scaffolds, evidence, search, idempotency,
                            # unresolved-link detection, add-on install, final gate
```

The self test builds a throwaway repo under `$TMPDIR`, so it never touches a real project.

## Limits, stated honestly

- No GUI proof: the vault and its add-on are validated by format rules, not by a human looking at
  Obsidian. Open the vault once and check the graph groups and Bases render.
- `scan` seeds the vault from manifests, docs and git history. It does not read every source file and
  summarize it; that is a review task, not a generation task.
- The index is literal search. Good enough for "which note covers this", not a semantic engine.
- macOS/Linux. Windows would need the entry script's shebang replaced by a `python` call.
