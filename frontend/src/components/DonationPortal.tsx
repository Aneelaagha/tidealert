// The donation portal: donors offer supplies against the board's open needs, and an operator records what arrived.
// An offer is a claim typed in by a donor: nothing checks it is real, no goods move, no money is taken and no contact
// details are kept. An offer to a zone the isolation engine finds cut off is allowed and flagged, never hidden.

import { HandHeart, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { ApiError, api, type Needs, type Pledge, type Run } from '../lib/api';
import { OfflineError } from '../lib/connection';
import { fmtTime, label } from '../lib/format';
import { canClose, canOffer } from '../lib/pledges';
import { Muted, Tag } from './ui';

interface Props {
  run: Run;
  needs: Needs | null;
  needsError: string | null;
  operator: string;
  at: string | null; // the slider time: offers and closings are stamped with it
  onChanged: () => void;
  onClose: () => void;
}

const message = (e: unknown) => (e instanceof ApiError ? `HTTP ${e.status}: ${e.detail}` : e instanceof OfflineError ? e.message : String(e));

interface Row { zoneId: string; name: string; item: string; unpledged: number; remaining: number; access: string | null; since: string | null }

function OfferRow({ run, needs, row, donor, at, onChanged }: { run: Run; needs: Needs | null; row: Row; donor: string; at: string | null; onChanged: () => void }) {
  const [quantity, setQuantity] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const can = canOffer(needs, donor, quantity, row.unpledged);
  async function offer() {
    setBusy(true);
    setError(null);
    try {
      await api.offerSupplies({ run_id: run.id, zone_id: row.zoneId, item_type: row.item, quantity: Number(quantity), donor: donor.trim(),
                                at: run.mode === 'live' ? null : at });
      setQuantity('');
      onChanged();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <li className="rounded border border-white/10 bg-navy-deep/60 p-2">
      <div className="flex flex-wrap items-center gap-2">
        <b className="text-white">{label(row.item)}</b>
        <span><b>{row.unpledged.toLocaleString()}</b> still needed</span>
        <Muted>({row.remaining.toLocaleString()} open{row.remaining !== row.unpledged ? `, ${(row.remaining - row.unpledged).toLocaleString()} already offered` : ''})</Muted>
        <span className="text-slate-400">in {row.name}</span>
        {row.access === 'isolated' && <Tag tone="red">ZONE CUT OFF</Tag>}
        {row.access === 'possibly_isolated' && <Tag tone="amber">MAY BE CUT OFF</Tag>}
      </div>
      {row.access === 'isolated' && (
        <p className="mt-1 text-[10.5px] text-red-300">The engine finds every road route out of this zone flooded{row.since ? ` since ${fmtTime(row.since)}` : ''}.
          An offer is allowed, but supplies may not reach it by road, and this page can't say how else they could.</p>
      )}
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        <input value={quantity} onChange={(e) => setQuantity(e.target.value)} inputMode="numeric" placeholder="quantity you can give" aria-label={`Quantity of ${row.item} for ${row.name}`}
               disabled={!needs?.writable || busy} className="w-40 rounded border border-accent-cyan/30 bg-navy-deep p-0.5 text-[11px] text-slate-200 focus:border-accent-cyan focus:outline-none disabled:opacity-40" />
        <button disabled={!can.ok || busy} title={can.reason ?? undefined} onClick={() => void offer()}
                className="cursor-pointer rounded border border-accent-cyan/50 bg-cyan-950/40 px-2 py-0.5 text-[10px] font-bold uppercase text-accent-cyan transition hover:bg-cyan-900/50 disabled:cursor-not-allowed disabled:border-white/5 disabled:bg-navy-deep disabled:text-slate-600">
          Offer
        </button>
        {busy && <span className="text-slate-500">sending…</span>}
      </div>
      {error && <p className="mt-1 text-danger-red">{error}</p>}
    </li>
  );
}

function PledgeLine({ pledge, zoneName, needs, operator, at, onChanged }: { pledge: Pledge; zoneName: string; needs: Needs | null; operator: string; at: string | null; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const can = canClose(needs, operator);
  async function close(kind: 'received' | 'withdrawn') {
    setBusy(true);
    setError(null);
    try {
      await api.closePledge(pledge.id, { kind, actor: operator.trim(), at });
      onChanged();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  const btn = 'cursor-pointer rounded border px-2 py-0.5 text-[10px] font-bold uppercase transition disabled:cursor-not-allowed disabled:border-white/5 disabled:bg-navy-deep disabled:text-slate-600';
  return (
    <li className="rounded border border-white/10 bg-navy-deep/60 p-2">
      <div className="flex flex-wrap items-center gap-2">
        <Tag tone={pledge.status === 'offered' ? 'amber' : pledge.status === 'received' ? 'green' : 'plain'}>{pledge.status === 'offered' ? 'offered' : pledge.status}</Tag>
        <b className="text-white">{pledge.donor}</b> offered {pledge.quantity.toLocaleString()} {label(pledge.item_type)} to {zoneName}
        <Muted>at {fmtTime(pledge.offered_at)}{pledge.closed_at ? ` · ${pledge.status} ${fmtTime(pledge.closed_at)} by ${pledge.closed_by}` : ''}</Muted>
      </div>
      {pledge.note && <p className="text-slate-500">{pledge.note}</p>}
      {pledge.status === 'offered' && (
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <button disabled={!can.ok || busy} title={can.reason ?? undefined} onClick={() => void close('received')}
                  className={`${btn} border-safe-green/50 bg-safe-green/10 text-safe-green hover:bg-safe-green/25`}>Mark received</button>
          <button disabled={!can.ok || busy} title={can.reason ?? undefined} onClick={() => void close('withdrawn')}
                  className={`${btn} border-white/20 text-slate-300 hover:bg-white/10`}>Withdraw</button>
          {!can.ok && needs && <Muted>{can.reason}</Muted>}
        </div>
      )}
      {error && <p className="mt-1 text-danger-red">{error}</p>}
    </li>
  );
}

export function DonationPortal({ run, needs, needsError, operator, at, onChanged, onClose }: Props) {
  const [donor, setDonor] = useState('');
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const { rows, pledges } = useMemo(() => {
    const rows: Row[] = [], pledges: (Pledge & { zoneName: string })[] = [];
    for (const [zoneId, z] of Object.entries(needs?.zones ?? {})) {
      const name = z.name ?? zoneId.slice(0, 8);
      for (const i of z.items) if (i.unpledged > 0) rows.push({ zoneId, name, item: i.item_type, unpledged: i.unpledged, remaining: i.remaining, access: z.zone_access, since: z.access_since });
      for (const p of z.pledges) pledges.push({ ...p, zoneName: name });
    }
    // Reachable-as-far-as-known first, cut-off zones last; most needed first within each.
    const rank = (a: string | null) => (a === 'isolated' ? 2 : a === 'possibly_isolated' ? 1 : 0);
    rows.sort((a, b) => rank(a.access) - rank(b.access) || b.unpledged - a.unpledged);
    pledges.sort((a, b) => (a.status === 'offered' ? 0 : 1) - (b.status === 'offered' ? 0 : 1) || b.offered_at.localeCompare(a.offered_at));
    return { rows, pledges };
  }, [needs]);

  return (
    <div className="fixed inset-0 z-[60] flex justify-end bg-black/60" onClick={onClose} role="dialog" aria-modal="true" aria-label="Donation portal">
      <div className="custom-scrollbar h-full w-full max-w-2xl overflow-y-auto border-l border-accent-cyan/25 bg-navy-panel p-5 font-mono text-[11px] text-slate-300"
           onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-white">
            <HandHeart className="h-4 w-4 text-accent-cyan" /> Donation portal
          </h2>
          <button onClick={onClose} aria-label="Close" className="cursor-pointer rounded p-1 text-slate-400 hover:text-white"><X className="h-4 w-4" /></button>
        </div>
        <p className="mb-3 font-sans text-[12px] leading-relaxed text-slate-300">
          Offer supplies against what operators say zones need{needs ? ` as of ${fmtTime(needs.at)}` : ''}. <b>No money is taken, no goods move, and no contact details are kept</b>:
          an offer is a claim typed in here, and an operator records what actually arrived. There is no login.
        </p>

        {needsError ? <p className="text-danger-red">{needsError}</p>
          : !needs ? <p className="text-slate-500">loading…</p>
          : !needs.writable ? <p className="rounded border border-white/10 p-2 text-slate-400">Off for this run: {needs.blocked_reason}</p>
          : (
            <>
              <label className="mb-3 flex flex-wrap items-center gap-2">
                <span className="uppercase text-slate-500">Your name or organisation</span>
                <input value={donor} onChange={(e) => setDonor(e.target.value)} maxLength={60} placeholder="shown with your offer; no email or phone"
                       className="min-w-0 flex-1 rounded border border-accent-cyan/30 bg-navy-deep p-1 text-[11px] text-slate-100 placeholder-slate-600 focus:border-accent-cyan focus:outline-none" />
              </label>

              <h3 className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-accent-cyan">Open needs ({rows.length})</h3>
              {rows.length ? <ul className="space-y-1.5">{rows.map((r) => <OfferRow key={`${r.zoneId}:${r.item}`} run={run} needs={needs} row={r} donor={donor} at={at} onChanged={onChanged} />)}</ul>
                : <p className="text-slate-500">Nothing is open and unoffered at this time. Operators enter needs in a zone's panel.</p>}

              <h3 className="mb-1.5 mt-4 text-[11px] font-bold uppercase tracking-wider text-accent-cyan">Offers ({pledges.length})</h3>
              {pledges.length ? <ul className="space-y-1.5">{pledges.map((p) => <PledgeLine key={p.id} pledge={p} zoneName={p.zoneName} needs={needs} operator={operator} at={at} onChanged={onChanged} />)}</ul>
                : <p className="text-slate-500">No offers at this time.</p>}
              <p className="mt-2 text-slate-500">Marking an offer received also records that much of the need as delivered. Operators close offers under the name in the Operator bar.</p>
            </>
          )}
      </div>
    </div>
  );
}
