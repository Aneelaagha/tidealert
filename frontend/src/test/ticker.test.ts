import { describe, expect, it } from 'vitest';
import { latestEvents } from '../components/EventTicker';
import type { Task } from '../lib/api';

const task = (id: string, times: string[]): Task => ({
  id, case_id: 'c', kind: 'welfare_check', created_at: times[0], created_by_rule: 'R1', status: 'pending',
  priority: 'medium', verify_before_dispatch: false, assigned_responder_id: null, active: true,
  events: times.map((at) => ({ at, status: 'pending', priority: 'medium', verify_before_dispatch: false,
                                actor: 'engine', note: `note ${at}`, assigned_responder_id: null })),
});

describe('the task-event feed', () => {
  it('lists stored events newest first, across tasks, up to the limit', () => {
    const events = latestEvents([task('a', ['2026-09-10T14:15:00Z', '2026-09-10T16:00:00Z']),
                                 task('b', ['2026-09-10T15:00:00Z'])], 2);
    expect(events.map((e) => [e.task.id, e.at])).toEqual([['a', '2026-09-10T16:00:00Z'], ['b', '2026-09-10T15:00:00Z']]);
    expect(events[0].note).toBe('note 2026-09-10T16:00:00Z');
  });

  it('puts the later of two same-time events first', () => {
    const events = latestEvents([task('a', ['2026-09-02T19:00:00Z', '2026-09-02T19:00:00Z'])]);
    expect(events.map((e) => e.seq)).toEqual([1, 0]);
  });

  it('is empty when there are no tasks', () => {
    expect(latestEvents([])).toEqual([]);
  });
});
