#!/usr/bin/env node
/**
 * vault-forge launcher.
 *
 * The engine is a stdlib-only Python program shipped in this package (`./vault-forge` + `./vaultforge/`).
 * This shim exists so the tool can be run the way a JavaScript team installs things:
 *
 *     npx -y github:Arigatouz/vault-forge build
 *
 * It finds a Python 3 interpreter, forwards every argument, and passes the exit code straight through, so
 * `validate` still fails a CI step the same way it does when called directly.
 */
'use strict';

const { spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const root = path.resolve(__dirname, '..');
const entry = path.join(root, 'vault-forge');

if (!fs.existsSync(entry)) {
  console.error(`vault-forge: engine missing at ${entry}`);
  process.exit(2);
}

const candidates = [process.env.VAULT_FORGE_PYTHON, process.env.PYTHON, 'python3', 'python'].filter(
  Boolean,
);

let python = null;
for (const candidate of candidates) {
  const probe = spawnSync(candidate, ['-c', 'import sys; print(sys.version_info[0])'], {
    encoding: 'utf8',
  });
  if (!probe.error && probe.status === 0 && String(probe.stdout).trim() === '3') {
    python = candidate;
    break;
  }
}

if (!python) {
  console.error(
    'vault-forge: no Python 3 on PATH.\n' +
      'The engine is stdlib-only Python (3.9+). Install it, or point VAULT_FORGE_PYTHON at an interpreter:\n' +
      '  macOS:  brew install python3\n' +
      '  Debian: sudo apt install python3\n' +
      '  Windows: winget install Python.Python.3.12',
  );
  process.exit(2);
}

const result = spawnSync(python, [entry, ...process.argv.slice(2)], {
  stdio: 'inherit',
  env: { ...process.env, VAULT_FORGE_LAUNCHED_BY: 'npx' },
});

if (result.error) {
  console.error(`vault-forge: ${result.error.message}`);
  process.exit(2);
}
process.exit(result.status === null ? 1 : result.status);
