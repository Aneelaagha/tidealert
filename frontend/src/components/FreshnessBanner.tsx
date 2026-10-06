// Source freshness as of the slider time (/map/freshness) on one line, and the run's caveats behind a "Caveats (n)"
// control on that line: collapsed by default so the header stays quiet, one click to read them, and the choice is
// remembered. The run's mode badge stays in the header and the full text is in Data & ethics.

import { Time } from './ui';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';

import type { Freshness, Run } from '../lib/api';
import { type Connection, offlineSourceLabel } from '../lib/connection';
import { fmtAge, label } from '../lib/format';

const DOT: Record<string, string> = {
  fresh: 'bg-safe-green', stale: 'bg-danger-red', no_data: 'bg-slate-500', event_driven: 'bg-sky-500',
};

const CAVEATS_KEY = 'tidealert.caveatsOpen';

function storedOpen(): boolean {
  try { return window.localStorage.getItem(CAVEATS_KEY) === '1'; } catch { return false; }
}

export function FreshnessBanner({ run, freshness, conn }: { run: Run; freshness: Freshness | null; conn: Connection }) {
  const offline = conn.state === 'offline';
  const [open, setOpen] = useState(storedOpen);
  const toggle = () => {
    setOpen((o) => {
      try { window.localStorage.setItem(CAVEATS_KEY, o ? '0' : '1'); } catch { /* not remembered: still works for this visit */ }
      return !o;
    });
  };
  const notes = [...run.caveats, ...(freshness?.note ? [freshness.note] : [])];
  return (
    <div className="border-b border-accent-cyan/10 bg-navy-panel/80 px-6 py-1.5 text-xs text-slate-300" aria-live="polite">
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      {freshness ? (
        <>
          <b className="text-slate-200">Sources as of <Time t={freshness.at} />{offline ? ' (cached)' : ''}:</b>
          {freshness.sources.map((s) => {
            if (offline) {
              // A source's status can't be known without the server: replay and scenario keep their load-time
              // status, labelled cached; a live source reads unknown.
              const o = offlineSourceLabel(run.mode, s.status, conn.offlineSince);
              return (
                <span key={s.name} className="inline-flex items-center gap-1.5">
                  <span className={`h-2 w-2 rounded-full ${o.unknown ? 'bg-slate-500' : DOT[o.status] ?? 'bg-unstyled'}`} />
                  {s.name}: <b>{label(o.status)}</b> ({o.note})
                </span>
              );
            }
            const age = s.status === 'no_data' ? 'no data yet' : `last ${fmtAge(s.age_seconds)} ago`;
            const rule = s.status === 'event_driven' ? 'event-driven, not judged'
              : `stale after ${fmtAge(s.stale_after_seconds)}${s.stale_after_overridden ? ' (run override)' : ''}`;
            return (
              <span key={s.name} title={rule} className="inline-flex items-center gap-1.5">
                <span className={`h-2 w-2 rounded-full ${DOT[s.status] ?? 'bg-unstyled'}`} />
                {s.name}: <b>{label(s.status)}</b> ({age})
              </span>
            );
          })}
          {freshness.sources.length === 0 && <span className="text-slate-500">none tracked for this run</span>}
        </>
      ) : offline ? (
        <b className="text-slate-400">Sources: not loaded before the connection dropped</b>
      ) : (
        // While loading, the run's own sources hold their place, so the banner doesn't grow when the statuses
        // arrive and push the page down (a click aimed at the copilot's input could land beside it).
        <>
          <b className="text-slate-500">Sources: loading…</b>
          {run.sources.map((s) => (
            <span key={s.name} className="inline-flex items-center gap-1.5 text-slate-500">
              <span className="h-2 w-2 rounded-full bg-slate-700" />
              {s.name}: <b>loading…</b>
            </span>
          ))}
        </>
      )}
      {notes.length > 0 && (
        <button type="button" onClick={toggle} aria-expanded={open}
                className="ml-auto flex cursor-pointer items-center gap-1 rounded border border-warning-orange/30 px-1.5 py-px text-warning-orange hover:bg-orange-950/30">
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />} Caveats ({notes.length})
        </button>
      )}
    </div>
    {open && notes.length > 0 && <ul className="mt-1.5 space-y-0.5 text-slate-400">{notes.map((c) => <li key={c}>{c}</li>)}</ul>}
    </div>
  );
}
