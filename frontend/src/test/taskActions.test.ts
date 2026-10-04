import { describe, expect, it } from 'vitest';
import type { Responder, Run, Task } from '../lib/api';
import { canAssign, canComplete, verifyReason } from '../lib/taskActions';
import { filterCases } from '../components/AlertsPanel';

const run = (blocked: string | null = null) => ({ mode: blocked ? 'replay' : 'scenario', task_actions_blocked: blocked }) as Run;
const event = (verify: boolean, note: string) => ({ at: '2026-09-10T14:15:00Z', status: 'pending', priority: 'low',
  verify_before_dispatch: verify, actor: 'engine', note, assigned_responder_id: null });
const task = (over: Partial<Task> = {}): Task => ({ id: 't', case_id: 'c', kind: 'welfare_check', created_at: '', created_by_rule: 'R1',
  status: 'pending', priority: 'high', verify_before_dispatch: false, assigned_responder_id: null, active: true,
  events: [event(false, 'created')], ...over });
const available = [{ id: 'r', status: 'available' }] as Responder[];

describe('when task actions are offered', () => {
  it('shows the server\'s replay reason before anything else', () => {
    const reason = "run 'x' is a replay: ...";
    expect(canAssign(run(reason), task(), 'ana', available)).toEqual({ ok: false, reason });
    expect(canComplete(run(reason), task({ status: 'assigned' }), '')).toEqual({ ok: false, reason });
  });

  it('needs an operator name', () => {
    expect(canAssign(run(), task(), '  ', available).reason).toMatch(/enter your name/);
  });

  it('assigns only a pending, unflagged task when someone is available', () => {
    expect(canAssign(run(), task(), 'ana', available).ok).toBe(true);
    expect(canAssign(run(), task({ status: 'assigned' }), 'ana', available).reason).toMatch(/only a pending task/);
    expect(canAssign(run(), task(), 'ana', [{ id: 'r', status: 'assigned' }] as Responder[]).reason).toMatch(/no responder/);
  });

  it('gives a flagged task\'s stored reason', () => {
    const flagged = task({ verify_before_dispatch: true,
      events: [event(false, 'created'), event(true, 'R3: verify before dispatch: latest evidence contradicts the Case')] });
    expect(verifyReason(flagged)).toBe('R3: verify before dispatch: latest evidence contradicts the Case');
    expect(canAssign(run(), flagged, 'ana', available).reason).toMatch(/latest evidence contradicts/);
  });

  it('completes only an assigned or en-route task', () => {
    expect(canComplete(run(), task({ status: 'assigned' }), 'ana').ok).toBe(true);
    expect(canComplete(run(), task({ status: 'en_route' }), 'ana').ok).toBe(true);
    expect(canComplete(run(), task(), 'ana').reason).toMatch(/needs assigned or en route/);
  });
});

describe('the Cases list', () => {
  const c = (id: string, word: string, status: string, opened: string) =>
    ({ id, confidence_word: word, status, opened_at: opened }) as never;
  const cases = [c('a', 'stale_verify', 'open', '2026-09-10T14:00:00Z'), c('b', 'corroborated', 'in_progress', '2026-09-10T15:00:00Z'),
                 c('d', 'corroborated', 'open', '2026-09-10T14:30:00Z'), c('e', 'single_source', 'resolved', '2026-09-10T14:00:00Z')];
  const ids = (xs: { id: string }[]) => xs.map((x) => x.id);

  it('filters by Case status and sorts strongest word first, then oldest', () => {
    expect(ids(filterCases(cases, 'open'))).toEqual(['d', 'b', 'a']);
    expect(ids(filterCases(cases, 'closed'))).toEqual(['e']);
    expect(ids(filterCases(cases, 'all'))).toEqual(['d', 'b', 'e', 'a']);
  });
});
