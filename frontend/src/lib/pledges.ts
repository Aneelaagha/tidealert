// When an offer or a closing would certainly be refused, and why. Otherwise the server decides and its answer is
// shown as returned (it also refuses contact details in a donor name or note, which this does not try to guess).

import type { Needs } from './api';

export function canOffer(needs: Needs | null, donor: string, quantity: string, unpledged: number): { ok: boolean; reason: string | null } {
  if (!needs) return { ok: false, reason: 'the needs board is loading' };
  if (!needs.writable) return { ok: false, reason: needs.blocked_reason };
  if (!donor.trim()) return { ok: false, reason: 'enter a name or organisation to show (no contact details are kept)' };
  const n = Number(quantity);
  if (!quantity.trim() || !Number.isInteger(n) || n < 1) return { ok: false, reason: 'quantity must be a whole number of 1 or more' };
  if (n > unpledged) return { ok: false, reason: `only ${unpledged.toLocaleString()} is open and not already offered` };
  return { ok: true, reason: null };
}

export function canClose(needs: Needs | null, operator: string): { ok: boolean; reason: string | null } {
  if (!needs) return { ok: false, reason: 'the needs board is loading' };
  if (!needs.writable) return { ok: false, reason: needs.blocked_reason };
  if (!operator.trim()) return { ok: false, reason: 'enter your name in the Operator bar first (there is no login)' };
  return { ok: true, reason: null };
}
