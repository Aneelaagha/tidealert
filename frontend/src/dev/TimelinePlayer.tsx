// DEV ONLY. The timeline player both dev tools use: a clock you can play, pause, restart, skip and speed up, a current-line read-out for
// the narrator, a progress bar and a 3-2-1 countdown before Play. It knows nothing about maps or runs: a TOOL (the guided tour, or the
// demo conductor) supplies the steps and does the work on every tick; this file keeps the time and draws the controls.
// Never part of a production bundle (see DevOverlay for the gates).
import { type ReactNode, useEffect, useState } from 'react';

/** A clock that can be played, paused, sought and sped up. `now` is injectable so tests control it. */
export class PlayerClock {
  private base = 0; // timeline seconds when `mark` was taken
  private mark = 0; // now() when `base` was taken
  private playing = false;
  private rate = 1;
  constructor(readonly now: () => number = () => performance.now()) { this.mark = now(); }
  get isPlaying(): boolean { return this.playing; }
  get speed(): number { return this.rate; }
  /** Timeline seconds. */
  time(): number { return this.playing ? this.base + ((this.now() - this.mark) / 1000) * this.rate : this.base; }
  play(): void { if (this.playing) return; this.mark = this.now(); this.playing = true; }
  pause(): void { this.base = this.time(); this.playing = false; }
  seek(t: number): void { this.base = Math.max(t, 0); this.mark = this.now(); }
  setSpeed(x: number): void { this.base = this.time(); this.mark = this.now(); this.rate = x; }
  /** Stand still for `wallMs` of real time (a tool waiting on data): the timeline does not advance. */
  hold(wallMs: number): void { if (this.playing) this.mark += wallMs; }
}

export interface PlayerStep { at: number; label: string }
export interface Line { text: string; sub?: string; skipped?: boolean }
export type PlayerStatus = 'idle' | 'opening' | 'ready' | 'countdown' | 'running' | 'paused' | 'finished' | 'refused';

/** What a tool gives the player. */
export interface Tool {
  title: string;
  steps: PlayerStep[]; // the skip menu and the progress marks
  duration: number; // seconds of timeline
  start(): void; // Play pressed from the beginning (after the countdown)
  tick(): void; // called every 100 ms while running or paused; reads the clock
  seek(i: number): void; // skip to step i
  stop(): void;
  line(t: number): Line | null; // what the narrator reads now
  finished(): boolean;
}

export const SPEEDS = [0.5, 1, 1.5] as const;
export const COUNTDOWN_S = 3;

/** The index of the last step that has begun at `t`, or -1 before the first. */
export function stepIndexAt(steps: { at: number }[], t: number): number {
  let i = -1;
  for (let k = 0; k < steps.length; k++) if (steps[k].at <= t) i = k;
  return i;
}

export const fmtClock = (s: number): string => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

interface Props {
  title: string;
  steps: PlayerStep[];
  duration: number;
  clock: PlayerClock;
  status: PlayerStatus;
  line: Line | null;
  message: string | null; // a refusal or a notice
  countdown: number | null;
  onPlay(): void;
  onPause(): void;
  onRestart(): void;
  onSkip(i: number): void;
  onSpeed(x: number): void;
  extra?: ReactNode; // tool-specific controls above the player
}

export function TimelinePlayer({ title, steps, duration, clock, status, line, message, countdown, onPlay, onPause, onRestart, onSkip, onSpeed, extra }: Props) {
  const [, setTick] = useState(0);
  useEffect(() => { const id = window.setInterval(() => setTick((n) => n + 1), 100); return () => window.clearInterval(id); }, []);
  const t = Math.min(clock.time(), duration);
  const idx = stepIndexAt(steps, t);
  const running = status === 'running';
  const btn = 'rounded border border-fuchsia-400/50 px-2 py-0.5 disabled:opacity-40';
  return (
    <aside className="fixed bottom-2 right-2 z-[70] w-[30rem] max-w-[96vw] rounded border border-fuchsia-400/60 bg-black/92 p-2.5 text-xs text-fuchsia-100" aria-label={`Dev timeline player: ${title}`} data-dev-player>
      <p className="font-bold uppercase tracking-wider">DEV · {title} (off in production)</p>
      {extra}
      {countdown !== null && (
        <div className="my-2 flex items-center justify-center rounded border border-fuchsia-400/40 py-3 text-6xl font-black text-white" aria-live="assertive" data-dev-countdown>{countdown}</div>
      )}
      {message ? <p className="mt-1.5 rounded border border-orange-400/50 bg-orange-950/40 p-2 text-sm leading-snug text-orange-100" role="alert" data-dev-message>{message}</p> : null}
      {line && countdown === null && !message && (
        <div className="mt-1.5 rounded border border-white/15 bg-white/5 p-2" data-dev-line aria-live="polite">
          <p className="text-base font-semibold leading-snug text-white">{line.text}</p>
          {line.sub ? <p className="mt-1 text-[11px] leading-snug text-fuchsia-200/80">{line.sub}</p> : null}
        </div>
      )}
      <div className="mt-2 h-2 w-full overflow-hidden rounded bg-white/10" role="progressbar" aria-valuemin={0} aria-valuemax={Math.round(duration)} aria-valuenow={Math.round(t)}>
        <div className="h-full bg-fuchsia-400" style={{ width: `${duration > 0 ? (t / duration) * 100 : 0}%` }} />
      </div>
      <p className="mt-0.5 flex justify-between text-[11px] text-fuchsia-200/80"><span>{idx >= 0 ? `step ${idx + 1} / ${steps.length}` : `step 0 / ${steps.length}`} · {steps[idx]?.label ?? ''}</span><span>{fmtClock(t)} / {fmtClock(duration)} · {status}</span></p>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <button type="button" onClick={onPlay} disabled={running || status === 'countdown' || status === 'opening' || status === 'refused' || status === 'idle'} className={btn}>Play</button>
        <button type="button" onClick={onPause} disabled={!running} className={btn}>Pause</button>
        <button type="button" onClick={onRestart} disabled={status === 'opening' || status === 'idle'} className={btn}>Restart</button>
        <select aria-label="Skip to step" value="" onChange={(e) => { if (e.target.value !== '') onSkip(Number(e.target.value)); }} disabled={status === 'idle' || status === 'opening' || status === 'refused' || status === 'countdown'}
                className="rounded border border-fuchsia-400/50 bg-black px-1 py-0.5 disabled:opacity-40">
          <option value="">Skip to step ▾</option>
          {steps.map((s, i) => <option key={`${s.at}:${s.label}`} value={i}>{i + 1}. {s.label} ({fmtClock(s.at)})</option>)}
        </select>
        <span className="ml-auto flex items-center gap-1" aria-label="Speed (rehearsal)">
          {SPEEDS.map((x) => (
            <button key={x} type="button" onClick={() => onSpeed(x)} aria-pressed={clock.speed === x}
                    className={`rounded border px-1.5 py-0.5 ${clock.speed === x ? 'border-white bg-fuchsia-500/40 text-white' : 'border-fuchsia-400/50'}`}>{x}x</button>
          ))}
        </span>
      </div>
    </aside>
  );
}
