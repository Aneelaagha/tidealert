import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { LastCallPanel, ZoneLastCall } from '../components/LastCallPanel';
import type { LastCall, LastCallZone } from '../lib/api';
import { MAX_LEAD, NO_LEAD, fmtCountdown, parseMinutes, totalLead } from '../lib/lastCall';

const zone = (over: Partial<LastCallZone> = {}): LastCallZone => ({ zone_id: 'z1', zone_name: 'USGS-08074500 street block 01338ae7', status: 'counting',
  cutoff_at: '2017-08-27T19:45:00+00:00', last_call_at: '2017-08-27T18:45:00+00:00', minutes_to_last_call: 41, minutes_to_cutoff: 101, hindsight: true, was_reconnected: false, ...over });
const data = (over: Partial<LastCall> = {}): LastCall => ({ run_id: 'r', mode: 'replay', at: 't', label: 'x', available: true, reason: null,
  lead: { reply_minutes: 10, decision_minutes: 5, travel_minutes: 45, total_minutes: 60, note: 'Set by you, not measured' },
  counts: { counting: 1, passed: 1, cut_off: 130, reconnected: 20 }, zones: [zone(), zone({ zone_id: 'z2', zone_name: 'ZONE-B', status: 'passed', minutes_to_last_call: null, minutes_to_cutoff: 12 })], ...over });
const panel = (d: LastCall | null, extra: Record<string, unknown> = {}) => renderToStaticMarkup(createElement(LastCallPanel,
  { data: d, error: null, lead: { reply: 10, decision: 5, travel: 45 }, onLead: () => {}, onSelect: () => {}, selectedZoneId: null, ...extra }));

describe('the countdown', () => {
  it('reads minutes as a person reads a clock', () => {
    expect([fmtCountdown(0), fmtCountdown(41), fmtCountdown(60), fmtCountdown(75), fmtCountdown(120)]).toEqual(['0 min', '41 min', '1 h', '1 h 15 min', '2 h']);
  });
  it('accepts a whole number of minutes up to a day, treats an empty box as none, and refuses the rest', () => {
    expect([parseMinutes(''), parseMinutes(' '), parseMinutes('45'), parseMinutes(String(MAX_LEAD))]).toEqual([0, 0, 45, MAX_LEAD]);
    for (const t of ['-1', '1.5', 'x', String(MAX_LEAD + 1)]) expect(parseMinutes(t), t).toBeNull();
    expect(totalLead({ reply: 10, decision: 5, travel: 45 })).toBe(60);
    expect(totalLead(NO_LEAD)).toBe(0);
  });
});

describe('the Last call panel', () => {
  it('shows the soonest countdown big and the one past its last call, from the server\'s numbers', () => {
    const html = panel(data());
    expect(html).toContain('41 min');
    expect(html).toContain('to last call');
    expect(html).toContain('Last call passed');
    expect(html).toContain('cut off in 12 min');
    expect(html).not.toContain('set by you, not measured'); // the lead-time explanation is in the write-up, not on the screen
  });
  it('shows the short block name (the unique part) and keeps the full name on hover', () => {
    const html = panel(data());
    expect(html).toContain('title="USGS-08074500 street block 01338ae7"');
    expect(html).toContain('>street block 01338ae7<');
  });
  it('counts the zones in each state', () => {
    const html = panel(data());
    for (const n of ['>1</b> counting down', '>130</b> cut off', '>20</b> reconnected']) expect(html).toContain(n);
  });
  it('carries no replay or hindsight paragraph: that lives in docs/algorithms/last-call.md', () => {
    const html = panel(data());
    for (const t of ['known in hindsight', 'stand in for a forecast', 'Per zone, not per household', 'roads reopen']) expect(html).not.toContain(t);
  });
  it('with no lead set, shows no lead-time sentence', () => {
    expect(panel(data({ lead: { reply_minutes: 0, decision_minutes: 0, travel_minutes: 0, total_minutes: 0, note: '' } }), { lead: NO_LEAD })).not.toContain('last call is the cut-off time itself');
  });
  it('unavailable: gives the server\'s reason and draws no countdown', () => {
    const html = panel(data({ available: false, reason: 'The isolation engine has not run on this run. Unknown stays unknown.', zones: [] }));
    expect(html).toContain('Unknown stays unknown');
    expect(html).not.toContain('to last call</span>');
  });
  it('nothing counting down: says so rather than drawing an empty list', () => {
    const html = panel(data({ zones: [zone({ status: 'cut_off', minutes_to_last_call: null })], counts: { counting: 0, passed: 0, cut_off: 1, reconnected: 0 } }));
    expect(html).toContain('No zone is counting down at this time');
  });
  it('loading and error states', () => {
    expect(panel(null)).toContain('loading');
    expect(panel(null, { error: 'boom' })).toContain('boom');
  });
});

describe('one zone\'s last call in the zone panel', () => {
  const text = (z: LastCallZone | undefined) => renderToStaticMarkup(createElement(ZoneLastCall, { z }));
  it('says each state in plain words, and "no last call" for a zone with no recorded cut-off', () => {
    expect(text(zone())).toContain('41 min');
    expect(text(zone({ status: 'passed', minutes_to_cutoff: 9 }))).toContain('last call passed');
    expect(text(zone({ status: 'cut_off' }))).toContain('cut off since');
    expect(text(zone({ status: 'reconnected' }))).toContain('reconnected');
    expect(text(zone({ status: 'reconnected' }))).toContain('not a guarantee');
    expect(text(undefined)).toContain('no last call');
  });
});

describe('the wording keeps its limits', () => {
  const code = (f: string) => readFileSync(join(__dirname, '..', f), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  it('never says recovery, rescue-or-recovery, or that every channel is closed', () => {
    for (const f of ['components/LastCallPanel.tsx', 'lib/lastCall.ts']) expect(code(f), f).not.toMatch(/recovery|any channel|by any|no longer be reached|can no longer/i);
  });
  it('invents no time: no clock reads and no random values', () => {
    for (const f of ['components/LastCallPanel.tsx', 'lib/lastCall.ts']) expect(code(f), f).not.toMatch(/Date\.now|new Date|Math\.random/);
  });
});
