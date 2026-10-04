// When the page offers a task action, and why not when it doesn't. These mirror the server's rules
// (backend/app/services/task_actions.py) only to grey out buttons that would certainly be refused; the server
// still decides, and any 409/422 it returns is shown as given.

import type { Responder, Run, Task } from './api';

export interface Allowed { ok: boolean; reason: string | null }

const yes: Allowed = { ok: true, reason: null };
const no = (reason: string): Allowed => ({ ok: false, reason });

/** Reasons that block every action on the run, before looking at the task. */
function common(run: Run, operator: string): Allowed | null {
  if (run.task_actions_blocked) return no(run.task_actions_blocked); // the server's own words, from /runs
  if (!operator.trim()) return no('enter your name as operator first (there is no login: actions record who acted)');
  return null;
}

/** The note of the event that set the task's verify-before-dispatch flag, as stored. */
export function verifyReason(task: Task): string | null {
  for (let i = task.events.length - 1; i >= 0; i--) {
    const e = task.events[i], prev = task.events[i - 1];
    if (e.verify_before_dispatch && (!prev || !prev.verify_before_dispatch)) return e.note;
  }
  return null;
}

export function canAssign(run: Run, task: Task, operator: string, responders: Responder[]): Allowed {
  const blocked = common(run, operator);
  if (blocked) return blocked;
  if (task.status !== 'pending') return no(`task is ${task.status}; only a pending task can be assigned`);
  if (task.verify_before_dispatch) {
    return no(`flagged verify before dispatch (${verifyReason(task) ?? 'reason not in the history'}); `
      + 'clearing the flag is API-only for now');
  }
  if (!responders.some((r) => r.status === 'available')) return no('no responder is available');
  return yes;
}

export function canComplete(run: Run, task: Task, operator: string): Allowed {
  const blocked = common(run, operator);
  if (blocked) return blocked;
  if (task.status !== 'assigned' && task.status !== 'en_route') {
    return no(`task is ${task.status}; complete needs assigned or en route`);
  }
  return yes;
}
