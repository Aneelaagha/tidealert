// "Needs attention": the top flagged zones in the order of lib/attention.ts, one click to open one.

import { ListOrdered } from 'lucide-react';
import { type Attention, RULE } from '../lib/attention';
import { label } from '../lib/format';
import { Mono, Tag, Time } from './ui';

const GROUP_TEXT = ['Cut off, nobody assigned', 'Cut off, responder assigned', 'May be cut off', 'Active task', 'Flagged'];

export function AttentionList({ items, selectedZoneId, onSelect, limit = 10 }:
  { items: Attention[]; selectedZoneId: string | null; onSelect: (a: Attention) => void; limit?: number }) {
  return (
    <section className="flex h-[26rem] flex-col rounded-lg border border-accent-cyan/25 bg-navy-panel p-4">
      <h2 className="mb-1 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-white" title={RULE}>
        <ListOrdered className="h-4 w-4 text-accent-cyan" /> Needs attention
        <span className="ml-auto text-[11px] font-normal normal-case text-slate-500">{items.length ? `top ${Math.min(limit, items.length)} of ${items.length} flagged` : ''}</span>
      </h2>
      {!items.length ? <p className="py-2 text-sm text-slate-500">Nothing is flagged at this time.</p> : (
        <ol className="custom-scrollbar min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
          {items.slice(0, limit).map((a, i) => (
            <li key={a.zoneId}>
              <button type="button" onClick={() => onSelect(a)} aria-current={selectedZoneId === a.zoneId}
                      className={`flex w-full cursor-pointer items-start gap-2 rounded border px-2 py-1.5 text-left text-sm transition hover:border-accent-cyan/50 ${
                        selectedZoneId === a.zoneId ? 'border-accent-cyan bg-cyan-950/40' : 'border-white/10 bg-navy-deep/60'}`}>
                <span className="mt-0.5 w-5 shrink-0 text-right text-xs font-bold text-slate-500">{i + 1}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-slate-100"><Mono>{a.name}</Mono></span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-x-1 gap-y-0.5 text-xs text-slate-400">
                    <Tag tone={a.group === 0 ? 'red' : a.group === 1 ? 'amber' : a.group === 2 ? 'amber' : 'plain'}>{GROUP_TEXT[a.group]}</Tag>
                    {a.since && a.group <= 2 && <span>since <Time t={a.since} /></span>}
                    {a.priority && <span>task {a.priority}</span>}
                    {a.word && <span>· {label(a.word)}</span>}
                    {a.open > 0 && <span className="text-warning-orange">· {a.open.toLocaleString()} needed</span>}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
      <p className="mt-2 text-[11px] leading-snug text-slate-600">{RULE}</p>
    </section>
  );
}
