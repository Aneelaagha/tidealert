// Sentences for the Data & ethics panel, built from GET /data-practices. Every claim about people's data follows
// a flag or a count from the server, so the panel changes when the system does.

import type { Counts, DataPractices } from './api';

export function countLine(what: string, c: Counts): string {
  if (!c.total) return `No ${what} are recorded.`;
  if (!c.real) return `${c.total} ${what}, all synthetic (generated for testing, not real people).`;
  return `${c.total} ${what}: ${c.real} real, ${c.synthetic} synthetic.`;
}

export function exposedLine(dp: DataPractices): string {
  return dp.personal_fields_exposed.length
    ? `Returned by the API: ${dp.personal_fields_exposed.join(', ')}. This breaks the data policy.`
    : 'None of these is returned by any route: the map, Cases, tasks and copilot work at zone level.';
}

export function consentLine(dp: DataPractices): string {
  return dp.consent_collected
    ? 'The households table can record consent.'
    : 'Consent: not collected yet. There is no intake flow, so the system holds no consent records.';
}

export function authenticationLine(dp: DataPractices): string {
  return dp.authentication ? 'Routes require a login.' : 'No login: anyone who can reach the API can use it.';
}

/** The personal fields split by where they are stored: on households, or elsewhere (a responder's phone). */
export function personalFieldsByOwner(dp: DataPractices): { household: string[]; other: string[] } {
  const stored = new Set(dp.household_fields_stored);
  return { household: dp.personal_fields.filter((f) => stored.has(f)), other: dp.personal_fields.filter((f) => !stored.has(f)) };
}
