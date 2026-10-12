#!/usr/bin/env bash
# End-to-end self test: scaffold a throwaway repo, build the vault, search it, install a fake
# add-on, and assert the gate passes. No network, no Obsidian, no side effects outside $TMP.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${TMPDIR:-/tmp}/vault-forge-selftest"
FAILURES=0

pass() { printf 'ok      %s\n' "$1"; }
fail() { printf 'FAIL    %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
check() { if [ "$2" = "$3" ]; then pass "$1 ($2)"; else fail "$1 (got '$2', want '$3')"; fi; }

rm -rf "$WORK"
mkdir -p "$WORK/demo-app/src" "$WORK/demo-app/docs" "$WORK/fake-addon"
cd "$WORK/demo-app"
git init -q .
git -c user.email=t@example.com -c user.name=t commit -q --allow-empty -m "chore: first commit"

cat > package.json <<'JSON'
{
  "name": "demo-app",
  "version": "1.0.0",
  "scripts": {"test": "vitest run", "verify": "npm run lint && npm test"},
  "dependencies": {"@angular/core": "^22.0.0", "rxjs": "^7.8.0"},
  "devDependencies": {"typescript": "^5.8.0", "vitest": "^3.0.0"}
}
JSON
cat > README.md <<'MD'
# Demo App

A tiny fixture used to prove vault-forge works end to end.
MD
printf 'export const answer = 42;\n' > src/app.ts
printf '# Decisions\n\n- 0001 use signals\n' > docs/decisions.md

printf '{"id":"fake-addon","name":"Fake Addon","version":"1.0.0","minAppVersion":"1.0.0","description":"fixture","author":"t","isDesktopOnly":true}\n' > "$WORK/fake-addon/manifest.json"
printf 'module.exports = {};\n' > "$WORK/fake-addon/main.js"

# 1. build
if "$ROOT/vault-forge" build >"$WORK/build.log" 2>&1; then pass "build exits 0"; else fail "build exits 0"; cat "$WORK/build.log"; fi
grep -q "PASS: 0 errors" "$WORK/build.log" && pass "gate reports 0 errors" || fail "gate reports 0 errors"

# 2. scaffold contents
for path in docs-vault/README.md docs-vault/Home.md docs-vault/05-Dashboards/Dashboard.md \
            docs-vault/Templates/Note.md docs-vault/.obsidian/graph.json \
            "docs-vault/01-Projects/demo-app.md" "docs-vault/02-Areas/Frontend/Frontend.md" \
            docs-vault/06-Canvases/"Vault Overview.canvas" docs-vault/index/vault-index.json \
            docs-vault/index/chunks.jsonl .vault-forge/forge.json .vault-forge/vault-forge; do
  [ -e "$path" ] && pass "created $path" || fail "created $path"
done

# 3. evidence actually used
grep -q "Angular" "docs-vault/01-Projects/demo-app.md" && pass "stack read from package.json" \
  || fail "stack read from package.json"
grep -q "vitest run" "docs-vault/03-Resources/Repo Conventions.md" && pass "scripts read from package.json" \
  || fail "scripts read from package.json"

# 4. search returns a ranked hit with a line number
"$ROOT/vault-forge" search "vitest" --limit 3 >"$WORK/search.log" 2>&1 || true
grep -q "Repo Conventions" "$WORK/search.log" && pass "search finds the conventions chunk" \
  || fail "search finds the conventions chunk"
grep -qE ':[0-9]+ +\[' "$WORK/search.log" && pass "search prints path:line" || fail "search prints path:line"
"$ROOT/vault-forge" search "zzqqxx wwvvuu" --limit 3 >"$WORK/search2.log" 2>&1 || true
grep -q "no match" "$WORK/search2.log" && pass "search reports no match honestly" \
  || fail "search reports no match honestly"
grep -qE '\[[0-9.]+ [0-9]+/[0-9]+\]' "$WORK/search.log" && pass "search reports terms matched" \
  || fail "search reports terms matched"

# 5. idempotency: a second build touches no note
"$ROOT/vault-forge" build >"$WORK/build2.log" 2>&1 || true
grep -qE "kept: +[0-9]+ existing notes untouched" "$WORK/build2.log" && pass "second build keeps notes" \
  || fail "second build keeps notes"

# 6. broken link is caught
printf -- '---\ntype: note\nstatus: active\ntags: [concept]\ncreated: 2026-01-01\nupdated: 2026-01-01\npriority: low\n---\n# Broken\n\nSee [[Nonexistent Note]].\n\n## Related\n\n- [[Home]]\n' > "docs-vault/03-Resources/Broken.md"
if "$ROOT/vault-forge" validate --quiet >"$WORK/validate.log" 2>&1; then
  fail "validate fails on an unresolved link"
else
  pass "validate fails on an unresolved link"
fi
grep -q "unresolved link \[\[Nonexistent Note\]\]" "$WORK/validate.log" && pass "unresolved link is named" \
  || fail "unresolved link is named"
rm "docs-vault/03-Resources/Broken.md"

# 7. add-on install
"$ROOT/vault-forge" plugin install --source "$WORK/fake-addon" >"$WORK/plugin.log" 2>&1 || fail "plugin install runs"
[ -f "docs-vault/.obsidian/plugins/fake-addon/main.js" ] && pass "add-on files copied into the vault" \
  || fail "add-on files copied into the vault"
grep -q '"fake-addon"' docs-vault/.obsidian/community-plugins.json && pass "add-on listed in community-plugins.json" \
  || fail "add-on listed in community-plugins.json"

# 7b. a .NET solution with a Makefile: stack, target framework, make targets, build output skipped
NET="$WORK/dotnet-app"
mkdir -p "$NET/src/Api/obj/Debug" "$NET/src/Api/bin/Debug"
printf '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>\n' > "$NET/src/Api/Api.csproj"
printf 'Microsoft Visual Studio Solution File\n' > "$NET/CompanyAcademy.sln"
printf 'build:\n\tdotnet build\n\ntest:\n\tdotnet test\n' > "$NET/Makefile"
printf '# Company Academy\n\nAn internal learning platform with a Socratic AI tutor that teaches\nconcepts and sets exercises for each learner.\n' > "$NET/README.md"
printf 'public class Program { }\n' > "$NET/src/Api/Program.cs"
head -c 200000 /dev/urandom | base64 > "$NET/src/Api/obj/Debug/generated.g.cs"
cd "$NET" && git init -q . && git -c user.email=t@e.com -c user.name=t commit -q --allow-empty -m "chore: init"
"$ROOT/vault-forge" build >"$WORK/dotnet.log" 2>&1 || fail "dotnet fixture build"
grep -q "C# / .NET" "$WORK/dotnet.log" && pass "dotnet stack detected" || fail "dotnet stack detected"
grep -q "skipped:.*bin, obj\|skipped:.*obj" "$WORK/dotnet.log" && pass "dotnet build output skipped" \
  || fail "dotnet build output skipped"
grep -q "net10.0" "docs-vault/01-Projects/dotnet-app.md" && pass "target framework read from csproj" \
  || fail "target framework read from csproj"
grep -q "make build" "docs-vault/01-Projects/dotnet-app.md" && pass "Makefile targets become commands" \
  || fail "Makefile targets become commands"
grep -q "Socratic AI tutor that teaches concepts and sets exercises" "docs-vault/01-Projects/dotnet-app.md" \
  && pass "README summary keeps the whole paragraph" || fail "README summary keeps the whole paragraph"
grep -q "obj/Debug\|bin/Debug" "docs-vault/03-Resources/Codebase Map.md" && fail "build output leaked into the map" \
  || pass "build output stays out of the map"
cd "$WORK/demo-app"

# 8. the npx launcher and the GitHub install path
node "$ROOT/bin/vault-forge.js" --version >"$WORK/launcher.log" 2>&1 && pass "node launcher runs the engine" \
  || fail "node launcher runs the engine"
grep -q "vault-forge " "$WORK/launcher.log" && pass "launcher reports the version" || fail "launcher reports the version"
if node "$ROOT/bin/vault-forge.js" plugin install --from-github no-slash-value >"$WORK/badspec.log" 2>&1; then
  fail "a malformed --from-github spec is refused"
else
  pass "a malformed --from-github spec is refused"
fi
grep -q "owner/repo" "$WORK/badspec.log" && pass "the refusal names the expected form" \
  || fail "the refusal names the expected form"
if "$ROOT/vault-forge" plugin install --source "$WORK/fake-addon" --from-github Arigatouz/agent-dispatch >"$WORK/both.log" 2>&1; then
  fail "--source and --from-github together are refused"
else
  pass "--source and --from-github together are refused"
fi

# 9. final gate
"$ROOT/vault-forge" validate >"$WORK/final.log" 2>&1 && pass "final validate exits 0" || fail "final validate exits 0"

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "SELFTEST PASS"
else
  echo "SELFTEST FAIL: $FAILURES check(s)"
fi
exit "$FAILURES"
