// Validation: how the Harvey backtest did, from GET /validation/harvey. Every number comes from its stored source and
// is shown with the run, the event window and the file it was read from. The weak result is shown with the strong one.

import { FlaskConical, X } from 'lucide-react';
import { type ReactNode, useEffect, useState } from 'react';
import { type Validation, type ValidationFlagRow, type ValidationSource, api } from '../lib/api';
import { fmtTime } from '../lib/format';
import { Tag, Time } from './ui';

const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
const signed = (m: number | null) => (m === null ? 'n/a' : `${m > 0 ? '+' : m < 0 ? '−' : ''}${Math.abs(m).toLocaleString()} min`);

function Source({ s, extra }: { s: ValidationSource; extra?: string }) {
  return <p className="mt-1 text-xs text-slate-500">Source: <span className="font-mono">{s.file}</span> · {s.path}{extra ? ` · ${extra}` : ''}</p>;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="border-t border-navy-line pt-3"><h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-accent-cyan">{title}</h3>{children}</section>;
}

function FlagTable({ rows }: { rows: ValidationFlagRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[34rem] text-left text-xs">
        <thead className="text-slate-500"><tr><th className="py-1 pr-2 font-normal">Flag</th><th className="px-2 font-normal">Block groups flagged</th><th className="px-2 font-normal">Heavy-claims groups reached</th><th className="px-2 font-normal">Flagged that are heavy</th><th className="px-2 font-normal">Flagged with any claim</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.flag} className="border-t border-white/5"><td className="py-1 pr-2 text-slate-200">{r.flag}</td><td className="px-2">{r.flagged_bgs}</td>
              <td className="px-2 font-bold text-white">{pct(r.recall_heavy)}</td><td className="px-2">{pct(r.share_flagged_heavy)}</td><td className="px-2">{pct(r.precision_lb_any_claim)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ValidationPanel({ onClose }: { onClose: () => void }) {
  const [v, setV] = useState<Validation | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    api.validation(ctl.signal).then(setV).catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message); });
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => { ctl.abort(); window.removeEventListener('keydown', onKey); };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[60] flex justify-end bg-black/60" onClick={onClose} role="dialog" aria-modal="true" aria-label="Validation">
      <div className="custom-scrollbar h-full w-full max-w-3xl overflow-y-auto border-l border-accent-cyan/25 bg-navy-panel p-5 text-sm text-slate-300" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-white"><FlaskConical className="h-4 w-4 text-accent-cyan" /> Validation</h2>
          <button onClick={onClose} aria-label="Close" className="cursor-pointer rounded p-1 text-slate-400 hover:text-white"><X className="h-4 w-4" /></button>
        </div>
        {error ? <p className="text-danger-red">{error}</p> : !v ? <p className="text-slate-500">reading the stored results…</p> : (
          <div className="space-y-4">
            <div>
              <p className="text-base font-bold text-white">{v.event} backtest</p>
              <p className="text-xs text-slate-500">Run <span className="font-mono">{v.run}</span> · data window <Time t={v.data_window_utc[0]} /> to <Time t={v.data_window_utc[1]} /> · three Houston basins · one event</p>
            </div>
            <div className="space-y-2">
              {v.headline.map((h) => (
                <p key={h.kind} className={`rounded border p-2.5 ${h.kind === 'strength' ? 'border-safe-green/40 bg-emerald-950/20 text-emerald-100' : 'border-warning-orange/40 bg-orange-950/20 text-orange-100'}`}>
                  <b>{h.kind === 'strength' ? 'What held up: ' : 'What did not: '}</b>{h.text}
                </p>
              ))}
            </div>

            <Section title={v.lead.title}>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[34rem] text-left text-xs">
                  <thead className="text-slate-500"><tr><th className="py-1 pr-2 font-normal">Gauge</th><th className="px-2 font-normal">Flood source</th><th className="px-2 font-normal">First road floods</th><th className="px-2 font-normal">First zone isolated</th><th className="px-2 font-normal">Alarm</th></tr></thead>
                  <tbody>
                    {v.lead.rows.map((g) => (
                      <tr key={g.site} className="border-t border-white/5 align-top">
                        <td className="py-1 pr-2 text-slate-200">{g.name}<br /><span className="font-mono text-slate-500">USGS {g.site}</span></td>
                        <td className="px-2">{g.flood_source} {g.verified ? <Tag tone="green">NWS map</Tag> : <Tag tone="amber">lower confidence</Tag>}</td>
                        <td className="px-2 font-bold text-white">{signed(g.first_road_floods_min)}{!g.verified && <span className="font-normal text-warning-orange"> (unverified)</span>}</td>
                        <td className="px-2">{signed(g.first_zone_isolated_min)}</td>
                        <td className="px-2"><Time t={g.alarm_minor_at} /><br /><span className="text-slate-500">{g.alarm_source}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {v.lead.rows.map((g) => <Source key={g.site} s={g.source} extra={`USGS ${g.site}`} />)}
            </Section>

            <Section title={v.zones.title}>
              <ul className="space-y-1">
                {v.zones.rows.map((z) => (
                  <li key={z.site}><b className="text-slate-200">{z.name}:</b> {Object.entries(z.status).filter(([, s]) => s.zones > 0).map(([k, s]) => `${k} ${s.zones.toLocaleString()} zones (${s.people.toLocaleString()} people)`).join(' · ')}</li>
                ))}
              </ul>
              <Source s={v.zones.rows[0].source} extra="same field in each gauge's file" />
            </Section>

            {v.hand.rows.length > 0 && (
              <Section title={v.hand.title}>
                <ul>{v.hand.rows.map((h) => <li key={h.site}><b className="text-slate-200">{h.name}:</b> median {h.median.toFixed(2)}, lowest {h.minimum.toFixed(2)}</li>)}</ul>
                <Source s={v.hand.rows[0].source} extra="same field in each gauge's file" />
              </Section>
            )}

            <Section title={v.nfip.title}>
              <p className="mb-2 text-xs text-slate-400">{v.nfip.definitions}</p>
              <p className="mb-1 font-bold text-slate-200">All {v.nfip.all.bgs} block groups ({v.nfip.all.heavy} heavy) · {pct(v.nfip.all.base_rate_any_claim)} of all groups had some claim</p>
              <FlagTable rows={v.nfip.all.rows} />
              <p className="mb-1 mt-3 font-bold text-slate-200">Only inside the river driver's coverage: {v.nfip.covered.bgs} groups ({v.nfip.covered.heavy} heavy), a very small sample</p>
              <FlagTable rows={v.nfip.covered.rows} />
              <Source s={v.nfip.source} extra={`executed ${fmtTime(v.nfip.executed_at)}`} />
            </Section>

            <Section title="What this does not show">
              <ul className="list-disc space-y-1 pl-5 text-slate-400">{v.limits.map((l) => <li key={l}>{l}</li>)}</ul>
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}
