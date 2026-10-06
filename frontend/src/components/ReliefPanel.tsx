// "Relief needs and pledges": what coordinators say each zone needs, and the pledges made against it, ranked by the zone's
// real isolation state. Every pledge is an unverified TEST entry: no payment, no delivery tracking, no identity. The bar and
// every number come from the server's answer. Replays refuse needs and pledges and say why.

import { Bed, BriefcaseMedical, Droplets, FlaskConical, HandCoins, type LucideIcon, Tent, Utensils } from 'lucide-react';
import { type FormEvent, useState } from 'react';
import { ApiError, api, type ReliefBoard, type ReliefNeed, type Run } from '../lib/api';
import { OfflineError } from '../lib/connection';
import { modeBadge } from '../lib/modes';
import { ACCESS_TONE, GOODS, NOTICE, canPledge, canPost, isOpen, overOpen } from '../lib/relief';
import { Mono } from './ui';

const ICON: Record<string, LucideIcon> = { water: Droplets, food: Utensils, shelter: Tent, blankets: Bed, medical: BriefcaseMedical };
const msg = (e: unknown) => (e instanceof ApiError ? e.detail : e instanceof OfflineError ? e.message : String(e));

interface Props {
  run: Run;
  board: ReliefBoard | null;
  error: string | null;
  operator: string;
  at: string | null;
  selectedZone: { id: string; name: string } | null; // the zone selected on the map, where a need is posted
  offline: boolean;
  mixed: Run | null; // the mixed scenario for the same event, offered on a replay
  onNeed: (n: ReliefNeed) => void; // the server's answer for a need just posted or pledged
  onSwitch: (id: string) => void;
}

export function NeedRow({ n }: { n: ReliefNeed }) {
  const Icon = ICON[n.item_type] ?? HandCoins;
  const tone = ACCESS_TONE[n.access.state] ?? ACCESS_TONE.not_evaluated;
  const done = n.status === 'filled' || n.status === 'closed';
  return (
    <li className={`rounded-md border border-white/10 bg-navy-deep/60 p-2.5 ${done ? 'opacity-70' : ''}`}>
      <div className="flex min-w-0 items-center gap-2">
        <Icon className="h-4 w-4 shrink-0 text-accent-cyan" aria-hidden="true" />
        <div className="min-w-0 flex-1 truncate text-sm">
          <b className="text-white">{n.item_label}</b> <span className="text-slate-400">for</span> <Mono>{n.zone_name}</Mono>
        </div>
        <span className="w-14 shrink-0 text-right text-sm font-bold tabular-nums text-white">{Math.round(n.percent)}%</span>
      </div>
      <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-white/10" role="progressbar" aria-valuemin={0} aria-valuemax={100}
           aria-valuenow={Math.round(n.percent)} aria-label={`${n.item_label} for ${n.zone_name}: ${n.quantity_pledged} of ${n.quantity_needed} ${n.unit} pledged`}>
        <div className={`h-full rounded-full ${tone.bar}`} style={{ width: `${Math.min(n.percent, 100)}%` }} />
      </div>
      <div className="mt-1.5 flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className="flex min-w-0 flex-wrap items-center gap-1.5 text-xs">
          <span className={`rounded border px-1.5 py-px ${tone.chip}`}>{n.access.label}</span>
          {n.status === 'filled' && <span className="rounded border border-safe-green/40 px-1.5 py-px text-emerald-200">filled</span>}
          {n.status === 'closed' && <span className="rounded border border-white/20 px-1.5 py-px text-slate-300">closed</span>}
          {n.is_synthetic && <span className="rounded border border-teal-300/40 px-1.5 py-px text-teal-200">synthetic</span>}
        </span>
        <span className="whitespace-nowrap text-xs tabular-nums text-slate-300">
          <b className="text-slate-100">{n.quantity_pledged.toLocaleString()}</b> / {n.quantity_needed.toLocaleString()} {n.unit} pledged
        </span>
      </div>
    </li>
  );
}

export function ReliefPanel({ run, board, error, operator, at, selectedZone, offline, mixed, onNeed, onSwitch }: Props) {
  const [needId, setNeedId] = useState('');
  const [qty, setQty] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [postItem, setPostItem] = useState<string>('water');
  const [postQty, setPostQty] = useState('');
  const openNeeds = (board?.needs ?? []).filter(isOpen);
  const chosen = openNeeds.find((n) => n.id === needId) ?? undefined;
  const can = canPledge(board, chosen, qty, offline);
  const canPostNeed = canPost(board, selectedZone?.id ?? null, operator, postQty, offline);
  const badge = modeBadge(run.mode);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!chosen) return;
    setBusy(true);
    setNote(null);
    try {
      const n = await api.pledgeToNeed(chosen.id, Number(qty), at);
      onNeed(n);
      setNote({ ok: true, text: `Pledged ${Number(qty).toLocaleString()} ${n.unit} (a test pledge).` });
      setQty('');
    } catch (err) {
      setNote({ ok: false, text: msg(err) });
    } finally {
      setBusy(false);
    }
  }

  async function postNeed(e: FormEvent) {
    e.preventDefault();
    if (!selectedZone) return;
    setBusy(true);
    setNote(null);
    try {
      const n = await api.postReliefNeed({ run_id: run.id, zone_id: selectedZone.id, item_type: postItem, quantity_needed: Number(postQty), created_by: operator.trim(), at });
      onNeed(n);
      setNeedId(n.id);
      setPostQty('');
      setNote({ ok: true, text: `Posted: ${n.quantity_needed.toLocaleString()} ${n.unit} of ${n.item_label.toLowerCase()} for ${n.zone_name}.` });
    } catch (err) {
      setNote({ ok: false, text: msg(err) });
    } finally {
      setBusy(false);
    }
  }

  const field = 'min-w-0 rounded border border-accent-cyan/30 bg-navy-deep p-1 text-sm text-slate-100 focus:border-accent-cyan focus:outline-none disabled:opacity-40';
  return (
    <section className="rounded-lg border border-accent-cyan/25 bg-navy-panel p-4" aria-label="Relief needs and pledges">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-white"><HandCoins className="h-4 w-4 text-accent-cyan" /> Relief needs and pledges</h2>
        <span className={`rounded border px-2 py-0.5 text-xs font-bold tracking-widest ${badge.className}`}>{badge.label}</span>
      </div>
      <p className="mt-1 flex items-center gap-1.5 text-sm font-semibold text-orange-200"><FlaskConical className="h-3.5 w-3.5 shrink-0" /> {NOTICE}</p>

      {error ? <p className="mt-2 text-sm text-danger-red">{error}</p>
        : !board ? <p className="mt-2 text-sm text-slate-500">loading…</p>
        : !board.writable ? (
          <div className="mt-3 rounded-md border border-white/10 bg-navy-deep/60 p-3 text-sm text-slate-300">
            <p>Needs and pledges are off for replays because they would invent a relief history.</p>
            {mixed && (
              <button type="button" onClick={() => onSwitch(mixed.id)}
                      className="mt-2 cursor-pointer rounded border border-teal-300/50 bg-teal-950/40 px-3 py-1 text-xs font-bold uppercase text-teal-200 hover:bg-teal-900/50">
                Switch to the mixed scenario
              </button>
            )}
          </div>
        ) : (
          <>
            {board.needs.length === 0 ? (
              <p className="mt-3 rounded-md border border-dashed border-white/15 p-3 text-sm text-slate-400">
                No needs posted yet. Select a zone on the map, then use <b className="text-slate-200">Post a need</b> below.
              </p>
            ) : (
              <ul className="mt-3 space-y-2" aria-label="Needs, most urgent first">{board.needs.map((n) => <NeedRow key={n.id} n={n} />)}</ul>
            )}

            <form onSubmit={submit} className="mt-3 flex flex-wrap items-end gap-2 border-t border-white/10 pt-3" aria-label="Pledge">
              <label className="flex min-w-0 flex-[2_1_14rem] flex-col gap-0.5 text-xs text-slate-400">Pledge against
                <select value={needId} onChange={(e) => setNeedId(e.target.value)} disabled={busy || !openNeeds.length} className={field}>
                  <option value="">{openNeeds.length ? 'pick an open need' : 'no open needs'}</option>
                  {openNeeds.map((n) => <option key={n.id} value={n.id}>{n.item_label}, {n.zone_name} ({n.quantity_open.toLocaleString()} {n.unit} open)</option>)}
                </select>
              </label>
              <label className="flex w-28 flex-col gap-0.5 text-xs text-slate-400">Quantity{chosen ? ` (${chosen.unit})` : ''}
                <input value={qty} onChange={(e) => setQty(e.target.value)} inputMode="numeric" placeholder="how many" disabled={busy || !chosen} className={`${field} tabular-nums`} />
              </label>
              <button type="submit" disabled={!can.ok || busy} title={can.reason ?? undefined}
                      className="cursor-pointer rounded border border-accent-cyan/50 bg-cyan-950/40 px-3 py-1.5 text-xs font-bold uppercase text-accent-cyan hover:bg-cyan-900/50 disabled:cursor-not-allowed disabled:border-white/5 disabled:bg-navy-deep disabled:text-slate-600">
                Pledge
              </button>
            </form>
            {!can.ok && (chosen || qty) && <p className="mt-1 text-xs text-slate-500">{can.reason}</p>}
            {can.ok && overOpen(chosen, qty) && chosen && <p className="mt-1 text-xs text-orange-200">That is more than the {chosen.quantity_open.toLocaleString()} {chosen.unit} still open: the server will refuse it.</p>}

            <details className="mt-3 rounded-md border border-white/10 bg-navy-deep/40 p-2.5">
              <summary className="cursor-pointer text-sm font-semibold text-slate-200">Post a need</summary>
              <form onSubmit={postNeed} className="mt-2 flex flex-wrap items-end gap-2" aria-label="Post a need">
                <p className="w-full text-xs text-slate-400">For the zone selected on the map: <b className="text-slate-200">{selectedZone ? <Mono>{selectedZone.name}</Mono> : 'none selected'}</b>. Posted under your name in the Operator bar.</p>
                <label className="flex min-w-0 flex-[1_1_9rem] flex-col gap-0.5 text-xs text-slate-400">Item
                  <select value={postItem} onChange={(e) => setPostItem(e.target.value)} disabled={busy} className={field}>
                    {GOODS.map((g) => <option key={g} value={g}>{board.items[g]?.label ?? g}</option>)}
                  </select>
                </label>
                <label className="flex w-28 flex-col gap-0.5 text-xs text-slate-400">Needed
                  <input value={postQty} onChange={(e) => setPostQty(e.target.value)} inputMode="numeric" placeholder={board.items[postItem]?.unit ?? 'quantity'} disabled={busy} className={`${field} tabular-nums`} />
                </label>
                <button type="submit" disabled={!canPostNeed.ok || busy} title={canPostNeed.reason ?? undefined}
                        className="cursor-pointer rounded border border-accent-cyan/50 bg-cyan-950/40 px-3 py-1.5 text-xs font-bold uppercase text-accent-cyan hover:bg-cyan-900/50 disabled:cursor-not-allowed disabled:border-white/5 disabled:bg-navy-deep disabled:text-slate-600">
                  Post need
                </button>
                {!canPostNeed.ok && <p className="w-full text-xs text-slate-500">{canPostNeed.reason}</p>}
              </form>
            </details>
          </>
        )}
      <div aria-live="polite" className="min-h-[1.25rem]">
        {note && <p className={`mt-2 text-sm ${note.ok ? 'text-emerald-200' : 'text-danger-red'}`}>{note.text}</p>}
      </div>
    </section>
  );
}
