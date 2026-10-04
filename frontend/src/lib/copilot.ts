// How the copilot panel labels things. Which intents need a selection comes from /copilot/status (`needs`), the
// same table the server checks; everything an answer says about itself comes from its response fields.

import type { CopilotAnswer } from './api';

export function intentAvailability(intent: string, needs: Record<string, string>, zoneId: string | null,
                                   caseId: string | null): { ok: boolean; reason: string | null } {
  const need = needs[intent];
  if (need === 'zone_id' && !zoneId) return { ok: false, reason: 'needs a zone: select one on the map' };
  if (need === 'case_id' && !caseId) return { ok: false, reason: 'needs a Case: pick one in the Cases panel' };
  return { ok: true, reason: null };
}

/** The badges and notes an answer carries, from its own fields. `statusMode` is the copilot's mode from /status:
 *  a template answer while the copilot is in model mode is a fallback, and says so. */
export function answerLabels(a: CopilotAnswer, statusMode: string) {
  return {
    badge: a.mode === 'model' ? 'MODEL' : a.mode === 'template' ? 'TEMPLATE' : a.mode.toUpperCase(),
    outOfScope: !a.in_scope,
    fellBack: a.mode === 'template' && statusMode === 'model',
    reason: a.mode_reason,
    servedBy: a.served_by ?? null,
    unknowns: a.unknowns ?? [],
    households: a.household_data && a.household_data.households > 0 ? a.household_data : null,
    retryAfter: a.retry_model_after_seconds ?? null,
  };
}
