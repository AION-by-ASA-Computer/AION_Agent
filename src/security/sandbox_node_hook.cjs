'use strict';
/**
 * Node preload: deny-by-default FS access for sandbox subprocesses.
 *
 * Loaded via ``node -r src/security/sandbox_node_hook.cjs script.js``.
 * Uses ``AION_SANDBOX_LL_READ`` / ``AION_SANDBOX_LL_WRITE`` from the environment.
 */
const fs = require('fs');
const path = require('path');

function splitPaths(raw) {
  return String(raw || '')
    .split(':')
    .map((p) => p.trim())
    .filter(Boolean);
}

function deniedPath(target) {
  const n = path.resolve(target);
  if (n.startsWith('/proc/') && !n.startsWith('/proc/self')) return true;
  if (n.startsWith('/sys/')) return true;
  return false;
}

function isUnder(root, target) {
  const rel = path.relative(root, target);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

function pathAllowed(target, write) {
  if (typeof target !== 'string') return true;
  if (deniedPath(target)) return false;
  const resolved = path.resolve(target);
  const roots = write ? splitPaths(process.env.AION_SANDBOX_LL_WRITE) : splitPaths(process.env.AION_SANDBOX_LL_READ);
  for (const root of roots) {
    if (isUnder(root, resolved)) return true;
  }
  return false;
}

function guardSync(name, write) {
  const orig = fs[name];
  if (typeof orig !== 'function') return;
  fs[name] = function guardedSync(...args) {
    const p = args[0];
    if (typeof p === 'string' && !pathAllowed(p, write)) {
      const err = Object.assign(new Error(`sandbox: filesystem access denied: ${p}`), { code: 'EACCES' });
      throw err;
    }
    return orig.apply(this, args);
  };
}

function guardAsync(name, write) {
  const orig = fs[name];
  if (typeof orig !== 'function') return;
  fs[name] = function guardedAsync(...args) {
    const p = args[0];
    if (typeof p === 'string' && !pathAllowed(p, write)) {
      const err = Object.assign(new Error(`sandbox: filesystem access denied: ${p}`), { code: 'EACCES' });
      if (typeof args[args.length - 1] === 'function') {
        args[args.length - 1](err);
        return;
      }
      return Promise.reject(err);
    }
    return orig.apply(this, args);
  };
}

[
  'readFileSync',
  'openSync',
  'readSync',
  'readdirSync',
  'statSync',
  'lstatSync',
  'accessSync',
  'existsSync',
].forEach((n) => guardSync(n, false));

[
  'writeFileSync',
  'appendFileSync',
  'mkdirSync',
  'rmSync',
  'unlinkSync',
  'writeSync',
].forEach((n) => guardSync(n, true));

['readFile', 'open', 'readdir', 'stat', 'lstat', 'access'].forEach((n) => guardAsync(n, false));
['writeFile', 'appendFile', 'mkdir', 'rm', 'unlink'].forEach((n) => guardAsync(n, true));
