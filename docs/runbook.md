# Runbook: put a vault in any project

One page, four steps, for any repository on this machine. Replace `<repo>` and `/path/to/vault-forge`.

## 0. One-time

```bash
git -C /path/to/vault-forge pull    # get the latest tool
bash /path/to/vault-forge/tests/selftest.sh   # optional, 26 checks
```

## 1. Create the vault inside the project repo

```bash
cd <repo>
/path/to/vault-forge init --name "My App" --areas "Architecture,Frontend" --tags "angular,tooling"
```

Writes `docs-vault/` (folders, templates, dashboards, Bases, canvas, `.obsidian` config, vault README)
and vendors the tool into `<repo>/.vault-forge/`. Settings land in `<repo>/.vault-forge/forge.json`.
Existing notes are never overwritten; `--force` re-renders template files only.

## 2. Install the add-on (the plugin that fires prompts at coding CLIs)

```bash
# once, if it is not built yet
cd /path/to/agent-dispatch && npm install && npm run build

cd <repo>
./.vault-forge/vault-forge plugin install --source /path/to/agent-dispatch
```

That copies `manifest.json`, `main.js`, `styles.css` into
`docs-vault/.obsidian/plugins/agent-dispatch/` and adds `agent-dispatch` to
`docs-vault/.obsidian/community-plugins.json`, which Obsidian honours on launch. Then, once:

1. Open the repo's `docs-vault/` folder as a vault in Obsidian (Open folder as vault).
2. Settings > Community plugins: the plugin appears as installed and enabled, because the registry file
   already lists it.
3. Optionally open the Agent Dispatch panel from the ribbon icon and set binary paths if they differ
   from the defaults.

Commit `docs-vault/.obsidian/plugins/agent-dispatch/` and every teammate gets the same add-on on
clone. The vault's own `.gitignore` keeps only per-user state out.

## 3. Draw the vault from the repository

```bash
cd <repo>
./.vault-forge/vault-forge build      # scan the repo, seed notes, build the index, run the gate
```

`build` reads `package.json`, `README.md`, `Cargo.toml`, `docs/`, the git log and the file tree, then
writes the project note, one MOC per area, the codebase map, the conventions note, the inbox, today's
daily note and the vault canvas. It finishes with the gate:

```
frontmatter   22        0
wikilinks     81        0
orphans       18        0
canvases       1        0
bases          4        0
index          1        0

PASS: 0 errors, 0 warning(s)
```

Re-running is safe: existing notes are kept (`kept: N existing notes untouched`). Use `scan --force`
only when you want the seeded notes rewritten from the current repo state.

## 4. Index it so agents reach files faster

```bash
./.vault-forge/vault-forge index                  # rebuild after note edits
./.vault-forge/vault-forge search "sidecar build" # ranked path:line hits + terms matched
./.vault-forge/vault-forge search "reactor" --json
./.vault-forge/vault-forge validate               # the gate; exit 1 on any error
```

Agents (Hermes, Claude Code, Codex, opencode) do this: read `docs-vault/index/index.md` first, run
`search` with `--json` for a hit list, then open only the cited lines with a normal file read. That is
the whole point of the index: fewer file reads per question, and a citation that is a path plus a line
number.

## Day-to-day rules for the team

- A note change that claims a behaviour change lands in the same commit as the code change.
- Never hand-edit `docs-vault/index/`; run `index`.
- Never edit `.obsidian/workspace.json`; the running app owns it and it is ignored by git.
- `validate` is the merge gate. Run it before pushing; a CI step can run it verbatim.

## When you are done

```bash
git add .vault-forge docs-vault
git commit -m "docs(vault): add the project knowledge vault"
```
