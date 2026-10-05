// One zone's operator-entered needs, and the form to enter them. Every entry says who entered it and when: it is a
// claim by a person, not a measurement. Greyed out with the server's reason where entries are refused (a replay).

import { ClipboardList } from 'lucide-react';
import { useState } from 'react';
import { ApiError, api, type Needs, type Run } from '../lib/api';
import { OfflineError } from '../lib/connection';
import { fmtTime, label } from '../lib/format';
import { canEnter } from '../lib/needs';
import { Muted, Tag } from './ui';

const ACTIONS = [['requested', 'Needed'], ['fulfilled', 'Delivered'], ['withdrawn', 'No longer needed']] as const;

interface Props {
  run: Run;
  zoneId: string;
  needs: Needs | null;
  needsError: string | null;
  operator: string;
  at: string | null; // the slider time: the entry is stamped with it
  onChanged: () => void;
}

export function NeedsBlock({ run, zoneId, needs, needsError, operator, at, onChanged }: Props) {
  const [item, setItem] = useState('water');
  const [event, setEvent] = useState<(typeof ACTIONS)[number][0]>('requested');
  const [quantity, setQuantity] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const can = canEnter(needs, operator, quantity);
  const z = needs && needs.at === at ? needs.zones[zoneId] : undefined;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.enterNeed({ run_id: run.id, zone_id: zoneId, item_type: item, event, quantity: Number(quantity),
                            actor: operator.trim(), at: run.mode === 'live' ? null : at, note: note.trim() });
      setQuantity('');
      setNote('');
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? `HTTP ${e.status}: ${e.detail}` : e instanceof OfflineError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const field = 'rounded border border-accent-cyan/30 bg-navy-deep p-0.5 text-[10px] text-slate-200 focus:border-accent-cyan focus:outline-none disabled:opacity-40';
  return (
    <div className="my-2 rounded border border-white/10 bg-navy-deep/60 p-2.5">
      <p className="flex items-center gap-1.5"><ClipboardList className="h-3.5 w-3.5 text-accent-cyan" />
        <b className="text-white">Needs</b> <Muted>entered by an operator, not measured</Muted></p>
      {needsError ? <p className="text-danger-red">{needsError}</p>
        : !needs || !z ? (needs ? <p className="text-slate-500">None entered at this time.</p> : <p className="text-slate-500">loading…</p>)
        : (
          <>
            <ul className="mt-1 space-y-0.5">
              {z.items.map((i) => (
                <li key={i.item_type}>
                  <Tag tone={i.remaining > 0 ? 'amber' : 'green'}>{label(i.item_type)}</Tag>
                  {i.remaining > 0 ? <b>{i.remaining.toLocaleString()} open</b> : <Muted>none open</Muted>}
                  <Muted> · asked {i.requested.toLocaleString()} · delivered {i.fulfilled.toLocaleString()} · withdrawn {i.withdrawn.toLocaleString()}{i.pledged > 0 ? ` · offered ${i.pledged.toLocaleString()}` : ''}</Muted>
                </li>
              ))}
            </ul>
            {z.pledges.length > 0 && (
              <ul className="mt-1 space-y-0.5 text-slate-400">
                {z.pledges.map((p) => (
                  <li key={p.id}><Tag tone={p.status === 'offered' ? 'amber' : p.status === 'received' ? 'green' : 'plain'}>{p.status}</Tag>
                    {p.donor}: {p.quantity.toLocaleString()} {label(p.item_type)} <Muted>({fmtTime(p.offered_at)})</Muted></li>
                ))}
              </ul>
            )}
            {z.zone_access === 'isolated' && <p className="mt-1 text-danger-red">This zone is cut off{z.access_since ? ` since ${fmtTime(z.access_since)}` : ''}: the engine finds every road route out flooded.</p>}
            {z.zone_access === 'possibly_isolated' && <p className="mt-1 text-warning-orange">This zone may be cut off.</p>}
            <details className="mt-1 text-slate-500">
              <summary className="cursor-pointer">Entries ({z.events.length})</summary>
              <ul className="mt-1 space-y-1 pl-3">
                {z.events.map((e) => (
                  <li key={e.id}>{fmtTime(e.at)} · {e.actor}: {label(e.event)} {e.quantity.toLocaleString()} {label(e.item_type)}{e.note ? ` (${e.note})` : ''}</li>
                ))}
              </ul>
            </details>
          </>
        )}
      <div className="mt-2 space-y-1.5 border-t border-white/10 pt-2">
        <div className="flex flex-wrap items-center gap-2">
          <select value={event} onChange={(e) => setEvent(e.target.value as typeof event)} aria-label="Entry kind" disabled={!needs?.writable || busy} className={field}>
            {ACTIONS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
          </select>
          <select value={item} onChange={(e) => setItem(e.target.value)} aria-label="Item" disabled={!needs?.writable || busy} className={field}>
            {(needs?.items ?? ['water']).map((i) => <option key={i} value={i}>{label(i)}</option>)}
          </select>
          <input value={quantity} onChange={(e) => setQuantity(e.target.value)} inputMode="numeric" placeholder="quantity" aria-label="Quantity"
                 disabled={!needs?.writable || busy} className={`${field} w-20`} />
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={needs?.max_note ?? 300} placeholder="note (no personal details)"
                 aria-label="Note" disabled={!needs?.writable || busy} className={`${field} min-w-0 flex-1`} />
          <button disabled={!can.ok || busy} title={can.reason ?? undefined} onClick={() => void submit()}
                  className="cursor-pointer rounded border border-accent-cyan/50 bg-cyan-950/40 px-2 py-0.5 text-[10px] font-bold uppercase text-accent-cyan transition hover:bg-cyan-900/50 disabled:cursor-not-allowed disabled:border-white/5 disabled:bg-navy-deep disabled:text-slate-600">
            Enter
          </button>
          {busy && <span className="text-slate-500">sending…</span>}
        </div>
        {!can.ok && needs && <p className="text-slate-500">{can.reason}</p>}
        {error && <p className="text-danger-red">{error}</p>}
        {can.ok && at && <p className="text-slate-600">Recorded at the slider time, {fmtTime(at)}, under your name. No login: anyone can enter.</p>}
      </div>
    </div>
  );
}
