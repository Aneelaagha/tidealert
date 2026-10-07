// DEV ONLY (?dev=1). The conductor's compact panel: three rows (Play / Pause / Restart, the read-along line, and a muted status row), a title bar
// that collapses it to a single "▶ Dev" tab (remembered in localStorage), and nothing else. The beats run as one sequence; their log goes to the
// console. UI only: the timeline, the events and the host are the conductor's own, unchanged.
import { useEffect, useState } from 'react';
import { SPEEDS, type Line, type PlayerClock, type PlayerStatus, fmtClock } from './TimelinePlayer';

export const SEQUENCE = ['isolation', 'listening', 'offline'] as const;
export const GAP_S = 2; // between one beat and the next

export const COLLAPSED_KEY = 'tidealert.devPanelCollapsed';
export function loadCollapsed(store: Pick<Storage, 'getItem'> | null = typeof window === 'undefined' ? null : window.localStorage): boolean {
  try { return store?.getItem(COLLAPSED_KEY) === '1'; } catch { return false; }
}
export function saveCollapsed(on: boolean, store: Pick<Storage, 'setItem'> | null = typeof window === 'undefined' ? null : window.localStorage): void {
  try { store?.setItem(COLLAPSED_KEY, on ? '1' : '0'); } catch { /* not remembered: the panel still works for this visit */ }
}

/** Whole-sequence totals from each beat's own length: the timeline seconds (with the gaps between beats) and the number of steps. */
export function sequenceTotals(durations: number[], stepCounts: number[]): { seconds: number; steps: number } {
  return { seconds: durations.reduce((a, b) => a + b, 0) + GAP_S * Math.max(durations.length - 1, 0), steps: stepCounts.reduce((a, b) => a + b, 0) };
}
/** Seconds elapsed in the sequence: the beats before this one (and their gaps) plus time into this one. Never past the total. */
export function elapsedIn(beatIndex: number, durations: number[], into: number): number {
  const before = durations.slice(0, beatIndex).reduce((a, b) => a + b, 0) + GAP_S * beatIndex;
  return Math.min(before + Math.max(into, 0), sequenceTotals(durations, []).seconds);
}

interface Props {
  clock: PlayerClock;
  status: PlayerStatus;
  line: Line | null;
  countdown: number | null;
  stepN: number;
  stepM: number;
  elapsed: number;
  total: number;
  onPlay(): void;
  onPause(): void;
  onRestart(): void;
  onSpeed(x: number): void;
}

export function CompactPanel({ clock, status, line, countdown, stepN, stepM, elapsed, total, onPlay, onPause, onRestart, onSpeed }: Props) {
  const [collapsed, setCollapsed] = useState(loadCollapsed);
  const [, tick] = useState(0);
  useEffect(() => { const id = window.setInterval(() => tick((n) => n + 1), 200); return () => window.clearInterval(id); }, []);
  const toggle = () => setCollapsed((c) => { saveCollapsed(!c); return !c; });
  if (collapsed) {
    return (
      <button type="button" onClick={toggle} aria-label="Open the dev conductor" data-dev-player data-dev-collapsed
              className="fixed bottom-2 right-2 z-[70] rounded border border-fuchsia-400/60 bg-black/92 px-2 py-1 text-xs font-bold text-fuchsia-100">▶ Dev</button>
    );
  }
  const running = status === 'running' || status === 'countdown' || status === 'opening';
  const btn = 'rounded border border-fuchsia-400/50 px-2.5 py-0.5 disabled:opacity-40';
  return (
    <aside className="fixed bottom-2 right-2 z-[70] w-80 rounded border border-fuchsia-400/60 bg-black/92 text-xs text-fuchsia-100" aria-label="Dev conductor" data-dev-player>
      <button type="button" onClick={toggle} aria-expanded="true" title="Collapse"
              className="flex w-full items-center justify-between border-b border-fuchsia-400/30 px-2 py-0.5 text-left text-[10px] font-bold uppercase tracking-wider">
        <span>▼ Dev conductor</span><span className="font-normal normal-case text-fuchsia-200/70">dev only</span>
      </button>
      <div className="space-y-1 p-1.5">
        <div className="flex gap-1.5">
          <button type="button" onClick={onPlay} disabled={running} className={btn}>Play</button>
          <button type="button" onClick={onPause} disabled={status !== 'running'} className={btn}>Pause</button>
          <button type="button" onClick={onRestart} disabled={status === 'opening'} className={btn}>Restart</button>
        </div>
        <div className="h-[3.2rem] overflow-y-auto text-[13px] leading-snug text-white" aria-live="polite" data-dev-line>
          {countdown !== null ? <span className="text-3xl font-black" data-dev-countdown>{countdown}</span>
            : line ? <>{line.text}{line.skipped ? <span className="text-fuchsia-200/60"> (skipped)</span> : null}</>
            : <span className="text-fuchsia-200/60">Press Play to run the three beats in order.</span>}
        </div>
        <div className="flex items-center justify-between text-[10px] text-fuchsia-200/60">
          <span>step {stepN} of {stepM} · {fmtClock(elapsed)} / {fmtClock(total)}</span>
          <span className="flex gap-1">
            {SPEEDS.map((x) => (
              <button key={x} type="button" onClick={() => onSpeed(x)} aria-pressed={clock.speed === x}
                      className={`rounded px-1 ${clock.speed === x ? 'bg-fuchsia-500/40 text-white' : ''}`}>{x}x</button>
            ))}
          </span>
        </div>
      </div>
    </aside>
  );
}
