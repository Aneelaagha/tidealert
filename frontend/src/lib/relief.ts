// Relief needs and pledges: what the form would certainly refuse, and the plain words for a need's state. The numbers
// (needed, pledged, open, percent) always come from the server's answer; nothing here computes or invents one.
// Everything is a PLEDGE: an unverified test entry. This file, like the panel, never says delivered, received or fulfilled.

import type { ReliefBoard, ReliefNeed } from './api';

export const NOTICE = 'Test pledges. No payment is processed.';
export const MAX_QUANTITY = 1_000_000;
export const GOODS = ['water', 'food', 'shelter', 'blankets', 'medical'] as const;

export const isOpen = (n: ReliefNeed) => n.status === 'open' || n.status === 'partial';

/** A whole number from 1 to `max`, or why not. */
export function checkQuantity(text: string, max: number): { ok: true; value: number } | { ok: false; reason: string } {
  const t = text.trim();
  const n = Number(t);
  if (!t) return { ok: false, reason: 'enter a quantity' };
  if (!Number.isInteger(n) || n < 1) return { ok: false, reason: 'quantity must be a whole number of 1 or more' };
  if (n > max) return { ok: false, reason: `only ${max.toLocaleString()} are open` };
  return { ok: true, value: n };
}

export function canPledge(board: ReliefBoard | null, need: ReliefNeed | undefined, quantity: string, offline: boolean): { ok: boolean; reason: string | null } {
  if (!board) return { ok: false, reason: 'the board is loading' };
  if (!board.writable) return { ok: false, reason: board.blocked_reason };
  if (offline) return { ok: false, reason: 'offline: the page is read-only until the connection returns' };
  if (!need) return { ok: false, reason: 'pick an open need' };
  if (!isOpen(need)) return { ok: false, reason: need.status === 'filled' ? 'this need is filled' : 'this need is closed' };
  // More than is open is NOT blocked here: the server refuses it with a 409 that states the open quantity, and that refusal is
  // what the person should see (the board may also have moved since this page last read it). overOpen() drives a hint.
  const q = checkQuantity(quantity, MAX_QUANTITY);
  return q.ok ? { ok: true, reason: null } : { ok: false, reason: q.reason };
}

/** True when the typed quantity is a whole number larger than what is still open on the need. */
export function overOpen(need: ReliefNeed | undefined, quantity: string): boolean {
  const n = Number(quantity.trim());
  return !!need && quantity.trim() !== '' && Number.isInteger(n) && n > need.quantity_open;
}

export function canPost(board: ReliefBoard | null, zoneId: string | null, operator: string, quantity: string, offline: boolean): { ok: boolean; reason: string | null } {
  if (!board) return { ok: false, reason: 'the board is loading' };
  if (!board.writable) return { ok: false, reason: board.blocked_reason };
  if (offline) return { ok: false, reason: 'offline: the page is read-only until the connection returns' };
  if (!zoneId) return { ok: false, reason: 'select a zone on the map first' };
  if (!operator.trim()) return { ok: false, reason: 'enter your name in the Operator bar first (there is no login)' };
  const q = checkQuantity(quantity, MAX_QUANTITY);
  return q.ok ? { ok: true, reason: null } : { ok: false, reason: q.reason };
}

/** Merge a need the server just returned into the board, replacing it by id or adding it. The server re-ranks on the next read. */
export function withNeed(board: ReliefBoard, need: ReliefNeed): ReliefBoard {
  const has = board.needs.some((n) => n.id === need.id);
  return { ...board, needs: has ? board.needs.map((n) => (n.id === need.id ? need : n)) : [...board.needs, need] };
}

export const ACCESS_TONE: Record<string, { chip: string; bar: string }> = {
  isolated: { chip: 'border-danger-red/50 bg-red-950/40 text-red-200', bar: 'bg-danger-red' },
  possibly_isolated: { chip: 'border-warning-orange/50 bg-orange-950/30 text-orange-200', bar: 'bg-warning-orange' },
  not_evaluated: { chip: 'border-white/20 bg-white/5 text-slate-300', bar: 'bg-slate-400' },
  reconnected: { chip: 'border-sky-400/50 bg-sky-950/30 text-sky-200', bar: 'bg-sky-400' },
  reachable: { chip: 'border-safe-green/50 bg-emerald-950/30 text-emerald-200', bar: 'bg-safe-green' },
};
