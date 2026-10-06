// Header: the run picker and its mode badge (runs.mode, as registered), the slider over the run's clock, and the
// sound controls. Every label here is either fixed UI text or a value from /runs.

import { FileText, FlaskConical, Radio, ShieldCheck, Volume2, VolumeX } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { Run } from '../lib/api';
import { isMuted, playTestTone, setMuted } from '../lib/audio';
import { fmtTime } from '../lib/format';
import { modeBadge } from '../lib/modes';


function span(r: Run) {
  return r.window_start ? `${fmtTime(r.window_start).slice(0, 10)} → ${fmtTime(r.window_end).slice(0, 10)}` : 'live';
}

interface Props {
  runs: Run[];
  run: Run | null;
  onRun: (id: string) => void;
  ticks: string[];
  tick: number;
  onTickInput: (i: number) => void;
  onTickCommit: () => void;
  onEthics: () => void;
  onReport: () => void;
  onValidation: () => void;
  onStart: (() => void) | null; // open the Harvey peak, framed, with the first case selected; null when no run has a recorded peak
}

export function Header({ runs, run, onRun, ticks, tick, onTickInput, onTickCommit, onEthics, onReport, onValidation, onStart }: Props) {
  const [muted, setMutedState] = useState(isMuted());
  const toggle = () => { setMuted(!muted); setMutedState(!muted); };
  // Keyboard stepping commits once the keys pause, not per key press: each commit refetches every zone
  // (about 650 kB gzipped for Harvey), and the server keeps computing requests the page has abandoned.
  const keyTimer = useRef<number | undefined>(undefined);
  const latestCommit = useRef(onTickCommit); // the timer must commit the slider's latest position, not a stale one
  latestCommit.current = onTickCommit;
  const commitSoon = () => {
    window.clearTimeout(keyTimer.current);
    keyTimer.current = window.setTimeout(() => latestCommit.current(), 400);
  };
  const commitNow = () => { window.clearTimeout(keyTimer.current); onTickCommit(); };
  useEffect(() => () => window.clearTimeout(keyTimer.current), []);

  return (
    <header className="sticky top-0 z-50 flex flex-col gap-3 border-b border-accent-cyan/20 bg-navy-deep/95 px-6 py-3 backdrop-blur-md lg:flex-row lg:items-center">
      <div className="flex items-center gap-3">
        <Radio className="h-7 w-7 shrink-0 text-accent-cyan" />
        <h1 className="text-sm font-black uppercase tracking-widest text-white">TideAlert</h1>
      </div>

      <div className="flex flex-1 flex-wrap items-center gap-3 text-xs">
        {onStart && (
          <button type="button" onClick={onStart} title="Open the flood at its worst, frame the map, and select the zone that needs attention first"
                  className="cursor-pointer rounded border border-accent-cyan bg-accent-cyan/15 px-3 py-1 text-xs font-bold uppercase tracking-wider text-accent-cyan hover:bg-accent-cyan/25">
            Start here
          </button>
        )}
        <label className="flex items-center gap-2 text-xs uppercase text-slate-400">
          Run
          <select value={run?.id ?? ''} onChange={(e) => onRun(e.target.value)}
                  className="max-w-[340px] rounded border border-navy-line bg-navy-panel p-1 text-[13px] normal-case text-slate-200 focus:border-accent-cyan/60 focus:outline-none">
            {runs.map((r) => <option key={r.id} value={r.id} title={r.name}>{r.description || r.name}, {span(r)}</option>)}
          </select>
        </label>
        {run && (
          <span title={run.caveats.join('\n')}
                className={`rounded border px-2 py-0.5 text-xs font-bold tracking-widest ${modeBadge(run.mode).className}`}>
            {modeBadge(run.mode).label}
          </span>
        )}
        <div className="flex min-w-[240px] flex-1 items-center gap-2 rounded border border-navy-line bg-navy-panel px-2.5 py-1">
          <input type="range" aria-label="Time" min={0} max={Math.max(ticks.length - 1, 0)} value={tick}
                 disabled={!ticks.length} className="h-1 flex-1 cursor-pointer accent-[#00f0ff]"
                 onChange={(e) => onTickInput(Number(e.target.value))}
                 onPointerUp={commitNow} onKeyUp={commitSoon} />
          <span className="whitespace-nowrap font-mono text-[13px] tabular-nums text-accent-cyan">
            {ticks.length ? fmtTime(ticks[tick]) : 'now (live)'}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2 ">
        <button onClick={onValidation}
                className="flex cursor-pointer items-center gap-1.5 rounded border border-accent-cyan/40 bg-cyan-950/30 px-2.5 py-1 text-xs font-bold uppercase tracking-widest text-accent-cyan transition hover:bg-cyan-900/50">
          <FlaskConical className="h-3.5 w-3.5" /> Validation
        </button>
        <button onClick={onReport} disabled={!run}
                className="flex cursor-pointer items-center gap-1.5 rounded border border-accent-cyan/40 bg-cyan-950/30 px-2.5 py-1 text-xs font-bold uppercase tracking-widest text-accent-cyan transition hover:bg-cyan-900/50 disabled:opacity-40">
          <FileText className="h-3.5 w-3.5" /> Report
        </button>
        <button onClick={onEthics}
                className="flex cursor-pointer items-center gap-1.5 rounded border border-accent-cyan/40 bg-cyan-950/30 px-2.5 py-1 text-xs font-bold uppercase tracking-widest text-accent-cyan transition hover:bg-cyan-900/50">
          <ShieldCheck className="h-3.5 w-3.5" /> Data & ethics
        </button>
        <button onClick={toggle}
                className={`flex cursor-pointer items-center gap-1.5 rounded border px-2.5 py-1 text-xs font-bold uppercase tracking-widest transition ${
                  muted ? 'border-white/10 bg-navy-panel text-slate-400 hover:text-slate-200'
                        : 'border-accent-cyan/40 bg-cyan-950/45 text-accent-cyan'}`}>
          {muted ? <VolumeX className="h-3.5 w-3.5" /> : <Volume2 className="h-3.5 w-3.5" />}
          {muted ? 'Sound off' : 'Sound on'}
        </button>
        <button onClick={playTestTone} disabled={muted} title={muted ? 'Turn sound on first' : 'Play a test tone'}
                className="cursor-pointer rounded border border-white/10 bg-navy-panel px-2.5 py-1 text-xs font-bold uppercase tracking-widest text-slate-400 transition hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-40">
          Sound test
        </button>
      </div>
    </header>
  );
}
