import { describe, expect, it } from 'vitest';
import type { CopilotAnswer } from '../lib/api';
import { answerLabels, intentAvailability } from '../lib/copilot';

const NEEDS = { zone_status: 'zone_id', zone_cases: 'zone_id', briefing: 'zone_id', explain_confidence: 'case_id' };
const answer = (over: Partial<CopilotAnswer> = {}): CopilotAnswer => ({
  mode: 'template', mode_reason: 'ANTHROPIC_API_KEY is not set: answers come from fixed templates', question: 'q',
  intent: 'zone_status', in_scope: true, answer: 'As of …', unknowns: [], tools: ['zone_status'], ...over });

describe('intent buttons', () => {
  it('follow the server\'s needs table', () => {
    expect(intentAvailability('open_cases', NEEDS, null, null).ok).toBe(true);
    expect(intentAvailability('zone_status', NEEDS, null, null).reason).toMatch(/select one on the map/);
    expect(intentAvailability('zone_status', NEEDS, 'z', null).ok).toBe(true);
    expect(intentAvailability('explain_confidence', NEEDS, 'z', null).reason).toMatch(/Cases panel/);
    expect(intentAvailability('explain_confidence', NEEDS, 'z', 'c').ok).toBe(true);
  });
});

describe('answer labels', () => {
  it('reads a no-key template answer as template mode, not a fallback or an error', () => {
    const l = answerLabels(answer(), 'template');
    expect(l.badge).toBe('TEMPLATE');
    expect(l.fellBack).toBe(false);
    expect(l.reason).toMatch(/ANTHROPIC_API_KEY is not set/);
  });

  it('marks a template answer given while the copilot is in model mode as a fallback, with its reason', () => {
    const l = answerLabels(answer({ mode_reason: 'model mode fell back to templates: rate limit …', retry_model_after_seconds: 42 }), 'model');
    expect(l.fellBack).toBe(true);
    expect(l.retryAfter).toBe(42);
  });

  it('carries model answers\' served_by, unknowns and household counts', () => {
    const l = answerLabels(answer({ mode: 'model', served_by: 'claude-opus-5-5', unknowns: ['t1.data_confidence'],
      household_data: { households: 7, real: 0, may_send_to_external_model: true } }), 'model');
    expect([l.badge, l.servedBy, l.unknowns, l.households?.real]).toEqual(['MODEL', 'claude-opus-5-5', ['t1.data_confidence'], 0]);
    expect(answerLabels(answer({ household_data: { households: 0, real: 0, may_send_to_external_model: true } }), 'template').households).toBeNull();
  });

  it('flags out-of-scope answers', () => {
    expect(answerLabels(answer({ in_scope: false, intent: null }), 'template').outOfScope).toBe(true);
  });
});
