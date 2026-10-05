// When the needs form would certainly be refused, and why. Otherwise the server decides and its answer is shown as
// returned. The needs themselves are operator-entered claims, never data the page or the server measured.

import type { Needs } from './api';

export function canEnter(needs: Needs | null, operator: string, quantity: string): { ok: boolean; reason: string | null } {
  if (!needs) return { ok: false, reason: 'the needs board is loading' };
  if (!needs.writable) return { ok: false, reason: needs.blocked_reason };
  if (!operator.trim()) return { ok: false, reason: 'enter your name in the Operator bar first (there is no login)' };
  const n = Number(quantity);
  if (!quantity.trim() || !Number.isInteger(n) || n < 1 || n > needs.max_quantity) {
    return { ok: false, reason: `quantity must be a whole number from 1 to ${needs.max_quantity.toLocaleString()}` };
  }
  return { ok: true, reason: null };
}
