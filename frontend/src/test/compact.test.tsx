import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { BEATS, SCRIPT, SCRIPT_LISTENING, SCRIPT_OFFLINE, readAlong } from '../dev/conductor';
import { COLLAPSED_KEY, CompactPanel, GAP_S, SEQUENCE, elapsedIn, loadCollapsed, saveCollapsed, sequenceTotals } from '../dev/CompactPanel';
import { PlayerClock } from '../dev/TimelinePlayer';

const props = { clock: new PlayerClock(() => 0), status: 'ready' as const, line: null, countdown: null, stepN: 0, stepM: 21, elapsed: 0, total: 117,
  onPlay: () => {}, onPause: () => {}, onRestart: () => {}, onSpeed: () => {} };
const html = (over = {}) => renderToStaticMarkup(<CompactPanel {...props} {...over} />);

describe('the compact panel', () => {
  it('has Play, Pause and Restart, the read-along, and the step, time and speed row: and nothing else', () => {
    const h = html({ line: { text: 'The first line.' }, stepN: 3, elapsed: 12, total: 117 });
    for (const w of ['Play', 'Pause', 'Restart', 'The first line.', 'step 3 of 21', '0:12 / 1:57', '0.5x', '1x', '1.5x']) expect(h).toContain(w);
    expect((h.match(/<button/g) ?? []).length).toBe(1 + 2 + 3 + 3); // the title bar, the two timeline tabs (Beats, Scene 2), the three controls, the three speeds
    for (const gone of ['Isolation beat', 'Silence + Listening', 'Offline beat', 'Open on Harvey', 'Recover', 'Reset', 'Skip to step', '<select', '<ul', 'progressbar']) expect(h).not.toContain(gone);
  });
  it('is about 320 px wide', () => { expect(html()).toContain('w-80'); });
  it('shows the countdown in the read-along row before Play', () => {
    const h = html({ status: 'countdown', countdown: 3 });
    expect(h).toContain('data-dev-countdown');
    expect(h).toMatch(/data-dev-countdown[^>]*>3</);
  });
  it('appends a muted (skipped) when a step was skipped, and not otherwise', () => {
    expect(html({ line: { text: 'A step.', skipped: true } })).toContain('(skipped)');
    expect(html({ line: { text: 'A step.' } })).not.toContain('(skipped)');
  });
  it('says what Play does before it is pressed', () => { expect(html()).toContain('Press Play to run the three beats in order.'); });
  it('disables Play while running and Pause unless running', () => {
    const running = html({ status: 'running' });
    expect(running).toMatch(/<button[^>]*disabled=""[^>]*>Play</);
    expect(html()).toMatch(/<button[^>]*disabled=""[^>]*>Pause</);
  });
});

describe('the Scene 2 tab', () => {
  it('has the two tabs, with Beats selected by default, and no Reset in the beats view', () => {
    const h = html();
    expect(h).toMatch(/role="tab" aria-selected="true"[^>]*>Beats</);
    expect(h).toMatch(/role="tab" aria-selected="false"[^>]*>Scene 2</);
    expect(h).not.toContain('>Reset<');
  });
  it('adds Reset and its own prompt in the Scene 2 view', () => {
    const h = html({ scene: 'scene2' });
    expect(h).toMatch(/role="tab" aria-selected="true"[^>]*>Scene 2</);
    expect(h).toContain('>Reset<');
    expect(h).toContain('Press Play to follow one coordinator through one decision.');
    expect((h.match(/<button/g) ?? []).length).toBe(1 + 2 + 4 + 3);
  });
  it('disables Reset and the tabs while a timeline runs, so nothing is deleted or switched mid-play', () => {
    const h = html({ scene: 'scene2', status: 'running' });
    expect(h).toMatch(/<button[^>]*disabled=""[^>]*>Reset</);
    expect(h).toMatch(/<button[^>]*disabled=""[^>]*>Beats</);
  });
});

describe('collapsing it', () => {
  const store = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); } }; };
  it('remembers collapsed and expanded in localStorage', () => {
    const s = store();
    expect(loadCollapsed(s)).toBe(false);
    saveCollapsed(true, s); expect(loadCollapsed(s)).toBe(true);
    saveCollapsed(false, s); expect(loadCollapsed(s)).toBe(false);
    expect(COLLAPSED_KEY).toBe('tidealert.devPanelCollapsed');
  });
  it('still works when storage is unavailable', () => {
    const broken = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
    expect(loadCollapsed(broken)).toBe(false);
    expect(() => saveCollapsed(true, broken)).not.toThrow();
    expect(loadCollapsed(null)).toBe(false);
  });
});

describe('the sequence', () => {
  it('is Beat 1, Beat 2, Beat 3 with a 2 second gap', () => {
    expect(SEQUENCE).toEqual(['isolation', 'listening', 'offline']);
    expect(GAP_S).toBe(2);
  });
  it('adds the gaps to the beat lengths for the total, and counts the steps of all three', () => {
    const durations = SEQUENCE.map((b) => BEATS[b].pacing.endAtS);
    const stepCounts = [SCRIPT, SCRIPT_LISTENING, SCRIPT_OFFLINE].map((s) => s.filter((e) => e.name !== 'silence').length);
    expect(sequenceTotals(durations, stepCounts)).toEqual({ seconds: 42 + 47 + 24 + 4, steps: 7 + 9 + 5 });
  });
  it('counts time into the sequence across beats and gaps, and never past the total', () => {
    const d = [42, 47, 24];
    expect(elapsedIn(0, d, 10)).toBe(10);
    expect(elapsedIn(1, d, 10)).toBe(42 + 2 + 10);
    expect(elapsedIn(2, d, 24)).toBe(42 + 2 + 47 + 2 + 24);
    expect(elapsedIn(2, d, 999)).toBe(117);
    expect(elapsedIn(0, d, -3)).toBe(0);
  });
});

describe('the read-along line', () => {
  it('is the narration, else the caption, else the step name', () => {
    expect(readAlong({ what: 'Narration.', caption: 'Caption.', name: 'step' })).toBe('Narration.');
    expect(readAlong({ what: ' ', caption: 'Caption.', name: 'step' })).toBe('Caption.');
    expect(readAlong({ name: 'step' })).toBe('step');
  });
  it('has a narration for every step of all three beats (so the fallbacks are never needed today)', () => {
    for (const e of [...SCRIPT, ...SCRIPT_LISTENING, ...SCRIPT_OFFLINE]) expect([e.name, e.what.trim().length > 0]).toEqual([e.name, true]);
  });
});

describe('the conductor overlay after the shrink', () => {
  const overlay = readFileSync(join(__dirname, '..', 'dev', 'DevOverlay.tsx'), 'utf8');
  it('mounts the compact panel for the conductor and the full player only for the tour', () => {
    expect(overlay).toMatch(/gate === 'dev' \? \(\s*<CompactPanel/);
    expect(overlay).toMatch(/<TimelinePlayer title="Guided tour"/);
  });
  it('sends the conductor\'s log to the console only: no list in the page', () => {
    expect(overlay).toMatch(/console\.info\(line\)/);
    expect(overlay).toMatch(/console\.warn\(line\)/);
    expect(overlay).not.toMatch(/<ul/);
  });
});
