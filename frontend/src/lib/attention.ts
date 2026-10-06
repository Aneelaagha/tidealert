// "Needs attention": the run's flagged zones in the order a responder should look at them. A display order built only
// from fields the API returns, never a score and not calibrated against outcomes. The rule, strictest first:
//   1. cut off, and no responder assigned to it
//   2. cut off, with someone assigned
//   3. may be cut off
//   4. anything else with an active task
//   5. the rest
// then, inside each group: task priority (high first), strongest Case confidence word, more open needs first, name.

import type { Case, Needs, ZonesResponse } from './api';

const PRIORITY = ['high', 'medium', 'low'];
const WORD = ['corroborated', 'single_source', 'stale_verify'];
const ACCESS_RANK: Record<string, number> = { isolated: 0, possibly_isolated: 1, reconnected: 2, reachable: 3, not_evaluated: 4 };

export interface Attention {
  zoneId: string;
  name: string;
  caseId: string | null; // the zone's strongest Case, for selecting it
  group: number;
  access: string | null; // the worst access state among the zone's active tasks, or null with no task
  since: string | null;
  assigned: boolean;
  priority: string | null;
  word: string | null;
  open: number; // open operator-entered need quantity in the zone
}

export const RULE = 'Order: cut off with nobody assigned, then cut off with someone assigned, then may be cut off, then other zones with an active task; inside each, by task priority, Case confidence, and open needs. A display order, not a risk score.';

export function rankAttention(zones: ZonesResponse | null, cases: Case[] | null, needs: Needs | null): Attention[] {
  if (!zones || !cases) return [];
  const names = new Map(zones.features.map((f) => [f.properties.zone_id, f.properties.name]));
  const byZone = new Map<string, Case[]>();
  for (const c of cases) byZone.set(c.zone_id, [...(byZone.get(c.zone_id) ?? []), c]);
  const out: Attention[] = [];
  for (const [zoneId, cs] of byZone) {
    const tasks = cs.flatMap((c) => c.tasks.filter((t) => t.active));
    let access: string | null = null, since: string | null = null;
    for (const t of tasks) {
      const a = t.safety?.zone_access ?? null;
      if (a && (access === null || (ACCESS_RANK[a] ?? 9) < (ACCESS_RANK[access] ?? 9))) { access = a; since = t.safety?.since ?? null; }
    }
    const assigned = tasks.some((t) => t.assigned_responder_id);
    const group = access === 'isolated' ? (assigned ? 1 : 0) : access === 'possibly_isolated' ? 2 : tasks.length ? 3 : 4;
    const priority = tasks.map((t) => t.priority).sort((a, b) => PRIORITY.indexOf(a) - PRIORITY.indexOf(b))[0] ?? null;
    const best = [...cs].sort((a, b) => WORD.indexOf(a.confidence_word) - WORD.indexOf(b.confidence_word))[0];
    out.push({ zoneId, name: names.get(zoneId) ?? zoneId.slice(0, 8), caseId: best?.id ?? null, group, access, since, assigned, priority,
               word: best?.confidence_word ?? null, open: needs?.zones[zoneId]?.open ?? 0 });
  }
  const p = (a: Attention) => (a.priority === null ? 9 : PRIORITY.indexOf(a.priority));
  const w = (a: Attention) => (a.word === null ? 9 : WORD.indexOf(a.word));
  return out.sort((a, b) => a.group - b.group || p(a) - p(b) || w(a) - w(b) || b.open - a.open || a.name.localeCompare(b.name));
}
