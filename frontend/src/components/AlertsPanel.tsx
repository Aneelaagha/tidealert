// The run's Cases as of the slider time, from /cases: engines, confidence word, zone, Case status, opened time.
// Selecting a Case selects its zone on the map and opens its active task's actions.

import { Radio } from 'lucide-react';
import { useState } from 'react';
import type { Case, Responder, Run } from '../lib/api';
import { UNSTYLED, colorOf } from '../lib/colors';
import { label } from '../lib/format';
import { SafetyNote, safetyTag } from './SafetyNote';
import { TaskActions } from './TaskActions';
import { Mono, Muted, Tag, Time } from './ui';

export type CaseFilter = 'open' | 'closed' | 'all';
const OPEN = ['open', 'in_progress'];
const WORD_ORDER = ['corroborated', 'single_source', 'stale_verify'];

export function filterCases(cases: Case[], filter: CaseFilter): Case[] {
  const kept = cases.filter((c) => filter === 'all' || (filter === 'open') === OPEN.includes(c.status));
  const rank = (w: string) => (WORD_ORDER.includes(w) ? WORD_ORDER.indexOf(w) : WORD_ORDER.length);
  return [...kept].sort((a, b) => rank(a.confidence_word) - rank(b.confidence_word)
    || Date.parse(a.opened_at) - Date.parse(b.opened_at));
}

interface Props {
  run: Run;
  at: string | null;
  cases: Case[] | null;
  error: string | null;
  zoneNames: Map<string, string>;
  selectedCaseId: string | null;
  onSelectCase: (c: Case | null) => void;
  operator: string;
  responders: Responder[];
  onActed: () => void;
}

export function AlertsPanel({ run, at, cases, error, zoneNames, selectedCaseId, onSelectCase, operator, responders, onActed }: Props) {
  const [filter, setFilter] = useState<CaseFilter>('open');
  const shown = cases ? filterCases(cases, filter) : [];
  const openCount = cases?.filter((c) => OPEN.includes(c.status)).length ?? 0;

  return (
    <section className="flex h-[420px] flex-col rounded-lg border border-accent-cyan/25 bg-navy-panel p-4 ">
      <div className="flex items-center justify-between gap-2 border-b border-navy-line pb-2.5">
        <h2 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-white">
          <Radio className="h-4 w-4 text-danger-red" /> Cases
          <span className="text-xs text-accent-cyan">({openCount} open or in progress)</span>
        </h2>
        <div className="flex gap-1.5 text-[11px] font-bold uppercase">
          {(['open', 'closed', 'all'] as const).map((f) => (
            <button key={f} onClick={() => setFilter(f)}
                    className={`cursor-pointer rounded border px-2 py-0.5 transition ${filter === f
                      ? 'border-danger-red/50 bg-red-500/15 text-danger-red' : 'border-white/5 bg-navy-deep/60 text-slate-400 hover:border-white/20'}`}>
              {f}
            </button>
          ))}
        </div>
      </div>

      <div className="custom-scrollbar mt-2 flex-1 space-y-1.5 overflow-y-auto pr-1 text-[13px]">
        {error ? <p className="text-danger-red">{error}</p>
          : !cases ? <p className="text-slate-500">loading Cases…</p>
          : !shown.length ? <p className="py-6 text-center text-slate-500">No {filter === 'all' ? '' : filter} Cases as of this time.</p>
          : shown.map((c) => {
            const selected = c.id === selectedCaseId;
            const active = c.tasks.filter((t) => t.active);
            return (
              <div key={c.id} onClick={() => onSelectCase(selected ? null : c)}
                   className={`cursor-pointer rounded border border-l-4 p-2.5 transition ${selected
                     ? 'border-accent-cyan/60 bg-navy-deep text-white' : 'border-white/10 bg-navy-deep/65 text-slate-300 hover:bg-[#121c32]/45'}`}
                   style={{ borderLeftColor: colorOf('confidence_word', c.confidence_word) ?? UNSTYLED }}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-bold">{c.confidence_word}</span>
                  <span className="text-slate-400"><Mono>{zoneNames.get(c.zone_id) ?? <Muted>zone {c.zone_id.slice(0, 8)}</Muted>}</Mono></span>
                </div>
                <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 border-t border-white/5 pt-1.5 text-xs text-slate-400 sm:grid-cols-3">
                  <div>STATUS: <span className="text-slate-200">{label(c.status)}</span></div>
                  <div>OPENED: <span className="text-slate-200"><Time t={c.opened_at} /></span></div>
                  <div>ENGINES: {c.engines.length ? c.engines.map((e) => <Tag key={e}>{e}</Tag>) : <Muted>none supporting</Muted>}</div>
                </div>
                {active.length > 0 && (
                  <div className="mt-1 text-xs text-slate-400">
                    {active.map((t) => (
                      <span key={t.id} className="mr-2">
                        TASK: <Tag tone="cyan">{label(t.status)}</Tag><Tag>{t.priority}</Tag>
                        {t.verify_before_dispatch && <Tag tone="amber">verify before dispatch</Tag>}
                        {safetyTag(t.safety)}
                      </span>
                    ))}
                  </div>
                )}
                {selected && (
                  <>
                    <p className="mt-2 font-sans text-slate-200">{c.inference_sentence}</p>
                    {active.length
                      ? active.map((t) => (
                          <div key={t.id}>
                            <p className="mt-2 text-xs text-slate-400">Task: {label(t.kind)} · {label(t.status)} · {t.priority}</p>
                            <SafetyNote safety={t.safety} />
                            <TaskActions run={run} task={t} operator={operator} at={at} responders={responders} onDone={onActed} />
                          </div>
                        ))
                      : <p className="mt-2 text-slate-500">No active task at this time.</p>}
                  </>
                )}
              </div>
            );
          })}
      </div>
    </section>
  );
}
