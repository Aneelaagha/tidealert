// Last call: the latest moment a dispatch could still set out before a zone's roads close = the engine's recorded cut-off
// time minus the lead time the OPERATOR sets (reply wait + decision + travel). The lead is a setting, not a measurement, so
// it is kept per viewer in the browser and shown with its arithmetic. Nothing here computes a time: the server does.

export interface Lead { reply: number; decision: number; travel: number }
export const NO_LEAD: Lead = { reply: 0, decision: 0, travel: 0 };
export const MAX_LEAD = 24 * 60;
const KEY = 'tidealert.lastCallLead';

/** A whole number of minutes from 0 to a day, or null when the text is not one (an empty box is 0). */
export function parseMinutes(text: string): number | null {
  const t = text.trim();
  if (t === '') return 0;
  const n = Number(t);
  return Number.isInteger(n) && n >= 0 && n <= MAX_LEAD ? n : null;
}

export const totalLead = (l: Lead) => l.reply + l.decision + l.travel;

/** "41 min", "1 h 15 min", "2 h": minutes as a person reads a countdown. */
export function fmtCountdown(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60), m = minutes % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function loadLead(): Lead {
  try {
    const raw = JSON.parse(window.localStorage.getItem(KEY) ?? 'null') as Lead | null;
    if (raw && [raw.reply, raw.decision, raw.travel].every((v) => Number.isInteger(v) && v >= 0 && v <= MAX_LEAD)) return raw;
  } catch { /* nothing remembered */ }
  return NO_LEAD;
}

export function saveLead(l: Lead): void {
  try { window.localStorage.setItem(KEY, JSON.stringify(l)); } catch { /* not remembered: still works for this visit */ }
}
