import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { NeedRow, ReliefPanel } from '../components/ReliefPanel';
import type { ReliefBoard, ReliefNeed, Run } from '../lib/api';
import { canPledge, canPost, checkQuantity, isOpen, overOpen, withNeed } from '../lib/relief';

const run = (over: Partial<Run> = {}): Run => ({ id: 'r', name: 'n', description: null, mode: 'mixed', event: 'Hurricane Harvey', peak_at: null, window_start: null, window_end: null,
  case_count: 0, regions: [], extent: null, caveats: [], task_actions_blocked: null, sources: [], ...over });
const need = (over: Partial<ReliefNeed> = {}): ReliefNeed => ({ id: 'n1', run_id: 'r', zone_id: 'z', zone_name: 'USGS-08074500 street block 01338ae7', item_type: 'water', item_label: 'Water',
  unit: 'litres', quantity_needed: 1200, quantity_pledged: 300, quantity_open: 900, percent: 25, status: 'partial', created_by: 'c', is_synthetic: false, created_at: '2026-10-06T00:00:00+00:00',
  access: { state: 'isolated', label: 'Cut off', since: null }, ...over });
const board = (over: Partial<ReliefBoard> = {}): ReliefBoard => ({ run_id: 'r', mode: 'mixed', at: 't', label: 'Test pledges. No payment is processed.', writable: true, blocked_reason: null,
  items: { water: { label: 'Water', unit: 'litres' }, food: { label: 'Food rations', unit: 'rations' }, shelter: { label: 'Shelter kits', unit: 'kits' }, blankets: { label: 'Blankets', unit: 'blankets' }, medical: { label: 'Medical kits', unit: 'kits' } },
  access_labels: {}, needs: [], ...over });
const panel = (b: ReliefBoard | null, extra: Record<string, unknown> = {}) => renderToStaticMarkup(createElement(ReliefPanel, {
  run: run(), board: b, error: null, operator: 'Sam', at: 't', selectedZone: null, offline: false, mixed: null, onNeed: () => {}, onSwitch: () => {}, ...extra }));

describe('a need row', () => {
  const html = renderToStaticMarkup(createElement(NeedRow, { n: need() }));
  it('shows item, zone, pledged / needed with units, the percentage and a progress bar with aria-valuenow', () => {
    expect(html).toContain('Water');
    expect(html).toContain('street block 01338ae7');
    expect(html).toContain('300</b> / 1,200 litres pledged');
    expect(html).toContain('25%');
    expect(html).toContain('role="progressbar"');
    expect(html).toContain('aria-valuenow="25"');
    expect(html).toContain('width:25%');
  });
  it('says the zone\'s access in plain words and keeps long text from overflowing (min-width and truncation)', () => {
    expect(html).toContain('Cut off');
    expect(html).toContain('min-w-0');
    expect(html).toContain('truncate');
    expect(html).toContain('tabular-nums');
  });
  it('uses the safety vocabulary for each state, and never colours not-assessed like a dry route', () => {
    const states = { isolated: 'Cut off', possibly_isolated: 'May be cut off', not_evaluated: 'Not assessed', reconnected: 'Reconnected, not a guarantee', reachable: 'Dry route' };
    for (const [state, label] of Object.entries(states)) expect(renderToStaticMarkup(createElement(NeedRow, { n: need({ access: { state, label, since: null } }) }))).toContain(label);
    const cls = (state: string) => renderToStaticMarkup(createElement(NeedRow, { n: need({ access: { state, label: state, since: null } }) })).match(/bg-(danger-red|warning-orange|slate-400|sky-400|safe-green)"/)?.[1];
    expect(cls('not_evaluated')).not.toBe(cls('reachable'));
  });
  it('marks filled, closed and synthetic needs, and caps the bar at 100%', () => {
    expect(renderToStaticMarkup(createElement(NeedRow, { n: need({ status: 'filled', percent: 100, quantity_pledged: 1200, quantity_open: 0 }) }))).toContain('filled');
    expect(renderToStaticMarkup(createElement(NeedRow, { n: need({ status: 'closed' }) }))).toContain('closed');
    expect(renderToStaticMarkup(createElement(NeedRow, { n: need({ is_synthetic: true }) }))).toContain('synthetic');
  });
});

describe('the panel states', () => {
  it('always shows the run-mode badge and the test-pledge line', () => {
    for (const b of [board(), board({ writable: false, blocked_reason: 'off' }), null]) {
      const html = panel(b);
      expect(html).toContain('Relief needs and pledges');
      expect(html).toContain('MIXED');
      expect(html).toContain('Test pledges. No payment is processed.');
    }
  });
  it('empty: says no needs posted yet and draws no placeholder bar', () => {
    const html = panel(board());
    expect(html).toContain('No needs posted yet');
    expect(html).not.toContain('role="progressbar"');
    expect(html).toContain('Post a need');
  });
  it('replay: explains why it is off and offers the mixed scenario, with no form', () => {
    const html = panel(board({ writable: false, blocked_reason: 'off for replays' }), { run: run({ mode: 'replay' }), mixed: run() });
    expect(html).toContain('off for replays because they would invent a relief history');
    expect(html).toContain('Switch to the mixed scenario');
    expect(html).not.toContain('aria-label="Pledge"');
    expect(html).not.toContain('role="progressbar"');
  });
  it('replay with no mixed run offers no switch', () => {
    expect(panel(board({ writable: false }), { run: run({ mode: 'replay' }) })).not.toContain('Switch to the mixed scenario');
  });
  it('lists the needs in the order the server gave, and only open ones in the pledge picker', () => {
    const html = panel(board({ needs: [need({ id: 'a', zone_name: 'ZONE-A' }), need({ id: 'b', zone_name: 'ZONE-B', status: 'filled', quantity_open: 0, percent: 100 })] }));
    expect(html.indexOf('ZONE-A')).toBeLessThan(html.indexOf('ZONE-B'));
    expect((html.match(/<option value="[ab]"/g) ?? []).length).toBe(1); // only the open need can be pledged against
  });
  it('never says delivered, received or fulfilled, and shows no donor identity field', () => {
    const html = panel(board({ needs: [need()] }));
    expect(html).not.toMatch(/deliver|receiv|fulfil/i);
    expect(html).not.toMatch(/name="(donor|email|phone)"|placeholder="(your )?(name|email|phone)/i);
  });
});

describe('the source files keep the honesty rules', () => {
  // The code only: the files' own comments say what they never do ("never delivered"), which is not the interface's wording.
  const read = (f: string) => readFileSync(join(__dirname, '..', f), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '').replace(/ \/\/ .*$/gm, '');
  it('say pledge, never delivered, received or fulfilled', () => {
    for (const f of ['components/ReliefPanel.tsx', 'lib/relief.ts']) expect(read(f), f).not.toMatch(/deliver|receiv|fulfil/i);
  });
  it('hardcode no needs and invent no values', () => {
    for (const f of ['components/ReliefPanel.tsx', 'lib/relief.ts']) expect(read(f), f).not.toMatch(/Math\.random|=\s*\[\s*\{/);
  });
});

describe('what the form would certainly refuse', () => {
  it('checks the quantity against the open amount and names it', () => {
    expect(checkQuantity('', 10)).toEqual({ ok: false, reason: 'enter a quantity' });
    for (const t of ['0', '-2', '1.5', 'x']) expect(checkQuantity(t, 10).ok, t).toBe(false);
    expect(checkQuantity('11', 10)).toEqual({ ok: false, reason: 'only 10 are open' });
    expect(checkQuantity('10', 10)).toEqual({ ok: true, value: 10 });
  });
  it('waits for the board, gives a replay\'s reason, refuses offline, and refuses a filled or closed need', () => {
    expect(canPledge(null, need(), '1', false).ok).toBe(false);
    expect(canPledge(board({ writable: false, blocked_reason: 'a replay' }), need(), '1', false)).toEqual({ ok: false, reason: 'a replay' });
    expect(canPledge(board(), need(), '1', true).reason).toContain('offline');
    expect(canPledge(board(), need({ status: 'filled' }), '1', false).reason).toBe('this need is filled');
    expect(canPledge(board(), need({ status: 'closed' }), '1', false).reason).toBe('this need is closed');
    expect(canPledge(board(), need(), '900', false)).toEqual({ ok: true, reason: null });
    // an over-pledge is not blocked in the form: the server's 409 (naming the open quantity) is what the person sees
    expect(canPledge(board(), need(), '901', false)).toEqual({ ok: true, reason: null });
    expect(overOpen(need(), '901')).toBe(true);
    expect([overOpen(need(), '900'), overOpen(need(), ''), overOpen(undefined, '5'), overOpen(need(), '1.5')]).toEqual([false, false, false, false]);
  });
  it('a need needs a selected zone, an operator name and a whole quantity', () => {
    expect(canPost(board(), null, 'Sam', '5', false).reason).toBe('select a zone on the map first');
    expect(canPost(board(), 'z', ' ', '5', false).ok).toBe(false);
    expect(canPost(board(), 'z', 'Sam', 'x', false).ok).toBe(false);
    expect(canPost(board(), 'z', 'Sam', '5', false)).toEqual({ ok: true, reason: null });
  });
  it('merges a need the server answered by id, or adds a new one, and knows what is open', () => {
    const b = board({ needs: [need({ id: 'a' }), need({ id: 'b' })] });
    expect(withNeed(b, need({ id: 'a', quantity_pledged: 900 })).needs.map((n) => n.quantity_pledged)).toEqual([900, 300]);
    expect(withNeed(b, need({ id: 'c' })).needs.map((n) => n.id)).toEqual(['a', 'b', 'c']);
    expect([isOpen(need({ status: 'open' })), isOpen(need({ status: 'partial' })), isOpen(need({ status: 'filled' })), isOpen(need({ status: 'closed' }))]).toEqual([true, true, false, false]);
  });
});
