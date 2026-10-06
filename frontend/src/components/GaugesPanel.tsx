// Current gauge readings: the latest values USGS has published for the project's gauges, read-only, with how old each
// is. It is labelled "current readings" and is NOT a live run: nothing here feeds the engines or is stored. If USGS (or
// the connection) is unavailable it says so and shows no value, never an old one.

import { Waves, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { type CurrentGauges, api } from '../lib/api';
import { fmtAge } from '../lib/format';
import { Tag, Time } from './ui';

const TONE = { fresh: 'green', stale: 'red', unknown: 'amber', unavailable: 'plain' } as const;

export function GaugesPanel({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<CurrentGauges | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    api.currentGauges(ctl.signal).then(setData).catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message); });
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => { ctl.abort(); window.removeEventListener('keydown', onKey); };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[60] flex justify-end bg-black/60" onClick={onClose} role="dialog" aria-modal="true" aria-label="Current gauge readings">
      <div className="custom-scrollbar h-full w-full max-w-2xl overflow-y-auto border-l border-accent-cyan/25 bg-navy-panel p-5 text-sm text-slate-300" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-white"><Waves className="h-4 w-4 text-accent-cyan" /> Current gauge readings</h2>
          <button onClick={onClose} aria-label="Close" className="cursor-pointer rounded p-1 text-slate-400 hover:text-white"><X className="h-4 w-4" /></button>
        </div>
        <p className="mb-3 rounded border border-white/10 bg-navy-deep/60 p-2 text-xs text-slate-400">
          The latest readings USGS has published for the gauges this project uses. <b className="text-slate-200">Not a live run:</b> nothing here feeds the engines
          or is stored, and the replays on this page are recorded data, not these readings. Provisional USGS data.
        </p>
        {error ? <p className="text-danger-red">Can't reach the TideAlert server, so there are no readings to show: {error}</p>
          : !data ? <p className="text-slate-500">asking USGS…</p>
          : !data.available ? (
            <p className="rounded border border-danger-red/40 bg-red-950/20 p-3 text-red-200"><b>Readings unavailable.</b> {data.reason} No value is shown rather than an old one. Fetched <Time t={data.fetched_at} />.</p>
          ) : (
            <>
              <ul className="space-y-2">
                {data.gauges.map((g) => (
                  <li key={g.site} className="rounded border border-white/10 bg-navy-deep/60 p-2.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <b className="text-white">{g.name}</b> <span className="font-mono text-xs text-slate-500">USGS {g.site}</span>
                      <Tag tone={TONE[g.status]}>{g.status}</Tag>
                      {g.age_seconds !== null && <span className="text-xs text-slate-400">newest reading {fmtAge(g.age_seconds)} old{g.stale_after_seconds ? ` (stale after ${fmtAge(g.stale_after_seconds)})` : ''}</span>}
                    </div>
                    {g.status === 'unavailable' ? <p className="mt-1 text-xs text-slate-500">No reading: {Object.values(g.readings).map((r) => r.error).filter(Boolean).join('; ')}</p> : (
                      <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-sm">
                        {Object.entries(g.readings).map(([k, r]) => (
                          <div key={k} className="contents">
                            <dt className="text-slate-500">{k}</dt>
                            <dd>{r.value !== undefined
                              ? <><b className="text-slate-100">{r.value.toLocaleString()} {r.unit?.replace('^3', '³')}</b> <span className="text-xs text-slate-500">observed <Time t={r.observed_at} />{r.approval ? ` · ${r.approval}` : ''}</span></>
                              : <span className="text-slate-500">no reading ({r.error})</span>}</dd>
                          </div>
                        ))}
                      </dl>
                    )}
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-slate-500">Fetched <Time t={data.fetched_at} /> from <span className="font-mono">{data.source}</span>. The server asks USGS at most once a minute.</p>
            </>
          )}
      </div>
    </div>
  );
}
