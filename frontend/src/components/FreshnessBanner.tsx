// Source freshness as of the slider time (/map/freshness) and the run's caveats, always visible.

import type { Freshness, Run } from '../lib/api';
import { type Connection, offlineSourceLabel } from '../lib/connection';
import { fmtAge, fmtTime, label } from '../lib/format';

const DOT: Record<string, string> = {
  fresh: 'bg-safe-green', stale: 'bg-danger-red', no_data: 'bg-slate-500', event_driven: 'bg-sky-500',
};

export function FreshnessBanner({ run, freshness, conn }: { run: Run; freshness: Freshness | null; conn: Connection }) {
  const offline = conn.state === 'offline';
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-accent-cyan/10 bg-navy-panel/80 px-6 py-1.5 font-mono text-[10.5px] text-slate-300"
         aria-live="polite">
      {freshness ? (
        <>
          <b className="text-slate-200">Sources as of {fmtTime(freshness.at)}{offline ? ' (cached)' : ''}:</b>
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
          {freshness.note && <span className="text-slate-500">{freshness.note}</span>}
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
      {run.caveats.map((c) => <span key={c} className="text-slate-500">{c}</span>)}
    </div>
  );
}
