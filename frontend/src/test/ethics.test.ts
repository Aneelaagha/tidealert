import { describe, expect, it } from 'vitest';
import type { DataPractices } from '../lib/api';
import { authenticationLine, consentLine, countLine, exposedLine, personalFieldsByOwner } from '../lib/ethics';

const dp = (over: Partial<DataPractices> = {}): DataPractices => ({
  households: { total: 33, real: 0, synthetic: 33 }, responders: { total: 8, real: 0, synthetic: 8 },
  household_fields_stored: ['id', 'contact_phone'], personal_fields: ['contact_phone'], personal_fields_exposed: [],
  write_routes: [], consent_collected: false, authentication: false,
  response_scan: { method: 'name-based', limitation: 'checked by name; …would not be caught.' },
  copilot: { mode: 'template', reason: 'no key', model: 'm', external_model_rule: 'rule' }, known_gaps: [], ...over });

describe('the panel states what the server reports, not fixed claims', () => {
  it('consent follows the consent_collected flag', () => {
    expect(consentLine(dp())).toMatch(/not collected yet/);
    expect(consentLine(dp({ consent_collected: true }))).not.toMatch(/not collected/);
  });

  it('exposure follows the computed exposed fields', () => {
    expect(exposedLine(dp())).toMatch(/None of these is returned/);
    expect(exposedLine(dp({ personal_fields_exposed: ['contact_phone'] }))).toMatch(/contact_phone.*breaks the data policy/);
  });

  it('authentication follows its flag', () => {
    expect(authenticationLine(dp())).toMatch(/No login/);
    expect(authenticationLine(dp({ authentication: true }))).toMatch(/require a login/);
  });

  it('counts say when everyone is synthetic, and when real people are present', () => {
    expect(countLine('households', dp().households)).toMatch(/all synthetic/);
    expect(countLine('households', { total: 34, real: 1, synthetic: 33 })).toBe('34 households: 1 real, 33 synthetic.');
    expect(countLine('responders', { total: 0, real: 0, synthetic: 0 })).toBe('No responders are recorded.');
  });

  it('splits personal fields by where they are stored (a responder\'s phone is not a household field)', () => {
    const split = personalFieldsByOwner(dp({ household_fields_stored: ['id', 'contact_phone', 'latitude'],
                                             personal_fields: ['contact_phone', 'latitude', 'phone'] }));
    expect(split).toEqual({ household: ['contact_phone', 'latitude'], other: ['phone'] });
  });
});
