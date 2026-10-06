import { describe, expect, it } from 'vitest';
import type { Run } from '../lib/api';
import { operatorMessage } from '../App';

const run = (over: Partial<Run>): Run => ({ id: 'r', name: 'n', description: null, mode: 'replay', event: 'Hurricane Harvey', peak_at: null, window_start: null, window_end: null,
  case_count: 0, regions: [], extent: null, caveats: [], task_actions_blocked: 'run n is a replay: its tasks show what the engines would have created', sources: [], ...over });

describe('the operator bar in plain words', () => {
  it('tells a replay\'s reader they can look but not change, names the event, and points to the mixed scenario', () => {
    const m = operatorMessage(run({}), run({ mode: 'mixed', task_actions_blocked: null }));
    expect(m.text).toContain('a replay of Hurricane Harvey');
    expect(m.text).toContain('look but not change anything');
    expect(m.text).toContain('mixed scenario');
    expect(m.why).toContain('replay'); // the server's own words stay available as a tooltip
  });

  it('does not offer a mixed scenario that does not exist', () => {
    expect(operatorMessage(run({}), null).text).not.toContain('mixed scenario');
  });

  it('says what the name is for on a run that takes actions', () => {
    const m = operatorMessage(run({ mode: 'mixed', task_actions_blocked: null }), null);
    expect(m.text).toContain('Your name is stamped');
    expect(m.why).toBeNull();
  });
});
