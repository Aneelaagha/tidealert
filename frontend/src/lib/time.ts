// The run's clock: slider stops over its window, and the run and time kept in the URL so a view can be shared.

import type { Run } from './api';

export const TICK_MS = 15 * 60 * 1000; // the case matcher's sweep cadence (a run doesn't store its own)

/** Slider stops for a run: every sweep from window start to end. A live run, or one without a window, has none. */
export function ticksFor(run: Pick<Run, 'mode' | 'window_start' | 'window_end'>): string[] {
  if (run.mode === 'live' || !run.window_start || !run.window_end) return [];
  const start = Date.parse(run.window_start), end = Date.parse(run.window_end);
  const ticks: string[] = [];
  for (let t = start; t <= end; t += TICK_MS) ticks.push(new Date(t).toISOString());
  return ticks;
}

/** The slider index for a requested time: that stop if it is one, else the end of the window. */
export function tickIndex(ticks: string[], at: string | null): number {
  if (!ticks.length) return 0;
  if (at) {
    const t = Date.parse(at);
    const i = Number.isNaN(t) ? -1 : ticks.indexOf(new Date(t).toISOString());
    if (i >= 0) return i;
  }
  return ticks.length - 1;
}

export function readUrl(search: string): { run: string | null; at: string | null } {
  const p = new URLSearchParams(search);
  return { run: p.get('run'), at: p.get('at') };
}

export function writeUrl(run: string, at: string | null): string {
  const p = new URLSearchParams({ run });
  if (at) p.set('at', at);
  return `?${p}`;
}
