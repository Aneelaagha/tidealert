// Permanent guard: the page shows only what the API returns. This scans every source file under src/ (tests
// excluded) for the ways the AI Studio reference app invented data, so none of them can come back unnoticed.
// It is a lexical check: it catches the patterns below, not every possible way to fake a value.

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '..');
const TEST_DIR = join(SRC, 'test');

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (path === TEST_DIR) return [];
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

const files = sources(SRC).map((path) => ({ path: relative(SRC, path), text: readFileSync(path, 'utf8') }));

function offenders(pattern: RegExp, allow: (path: string) => boolean = () => false): string[] {
  return files.filter((f) => !allow(f.path) && pattern.test(f.text)).map((f) => f.path);
}

describe('no invented data in src/', () => {
  it('scans the real source tree', () => {
    expect(files.map((f) => f.path)).toContain('App.tsx');
    expect(files.length).toBeGreaterThan(5);
  });

  it('never generates values at random', () => {
    expect(offenders(/Math\.random/)).toEqual([]);
  });

  it('never stamps the wall clock as data (times come from the API and the run clock)', () => {
    // The one exception is the connection state (offline mode): "offline since" and "loaded at" are times the
    // browser itself observed, which the API cannot supply. Only these three files read the clock, and only for that.
    const connection = ['App.tsx', join('lib', 'api.ts'), join('lib', 'connection.ts')];
    expect(offenders(/Date\.now\s*\(|new Date\s*\(\s*\)/, (p) => connection.includes(p))).toEqual([]);
  });

  it('talks to the backend only through src/lib/api.ts and the connection layer it sits on', () => {
    // lib/connection.ts holds the timeout wrapper and the reachability probe that api.ts calls through.
    expect(offenders(/\bfetch\s*\(/, (p) => p === join('lib', 'api.ts') || p === join('lib', 'connection.ts'))).toEqual([]);
  });

  it('names no outside host except the basemap tiles', () => {
    const allowed = ['https://tile.openstreetmap.org/', 'https://www.openstreetmap.org/copyright'];
    const found = files.flatMap((f) => (f.text.match(/https?:\/\/[^\s'"`)]+/g) ?? []).map((url) => `${f.path}: ${url}`));
    expect(found.filter((x) => !allowed.some((a) => x.split(': ')[1].startsWith(a)))).toEqual([]);
  });

  it('declares no hardcoded list of records', () => {
    // A module-level array of object literals is how the reference app seeded its fake sectors, alerts, responders,
    // routes and donations.
    expect(offenders(/=\s*\[\s*\{/)).toEqual([]);
  });

  it('depends on no outside model SDK and has no server of its own (the copilot is /copilot/ask)', () => {
    const pkg = JSON.parse(readFileSync(join(SRC, '..', 'package.json'), 'utf8'));
    const deps = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies });
    expect(deps.filter((d) => /genai|gemini|openai|anthropic|express|dotenv/i.test(d))).toEqual([]);
    expect(readdirSync(join(SRC, '..')).filter((f) => /^server\.(ts|js|cjs|mjs)$/.test(f))).toEqual([]);
  });

  it('carries none of the reference app\'s invented concepts or its persona', () => {
    const banned = /aegis|gemini|@google\/genai|txHash|signalDepth|sensorType|waterLevel|floodingTrend|crowdFlow|supplyRoute|personnelLeft|\bfuel\b|satellite|latency|rainIntensity/i;
    expect(offenders(banned)).toEqual([]);
  });

  it('keeps the word "donation" to the donation portal, which is backed by the API (the reference app\'s was invented)', () => {
    // The portal shows only what operators and donors typed in and the server stored (/needs, /pledges), labelled so.
    // Anywhere else the word would mean the reference app's fake donation board has come back.
    const portal = ['App.tsx', join('components', 'DonationPortal.tsx'), join('components', 'MapToolbar.tsx')];
    expect(offenders(/donation/i, (p) => portal.includes(p))).toEqual([]);
    expect(files.find((f) => f.path === join('components', 'DonationPortal.tsx'))?.text).toMatch(/api\.offerSupplies/);
  });
});
