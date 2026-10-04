// Source freshness as of the slider time (/map/freshness) and the run's caveats, always visible.

import type { Freshness, Run } from '../lib/api';
import { fmtAge, fmtTime, label } from '../lib/format';

const DOT: Record<string, string> = {
  fresh: 'bg-safe-green', stale: 'bg-danger-red', no_data: 'bg-slate-500', event_driven: 'bg-sky-500',
};

export function FreshnessBanner({ run, freshness }: { run: Run; freshness: Freshness | null }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-accent-cyan/10 bg-navy-panel/80 px-6 py-1.5 font-mono text-[10.5px] text-slate-300"
         aria-live="polite">
      {freshness ? (
        <>
          <b className="text-slate-200">Sources as of {fmtTime(freshness.at)}:</b>
          {freshness.sources.map((s) => {
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
      ) : <span className="text-slate-500">loading sources…</span>}
      {run.caveats.map((c) => <span key={c} className="text-slate-500">{c}</span>)}
    </div>
  );
}
