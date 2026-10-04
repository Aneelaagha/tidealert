// The footer feed: the run's task events up to the slider time, newest first, from /tasks. Each entry is a stored
// event (its own time, actor and note); nothing here is generated.

import { Layers } from 'lucide-react';
import type { Task } from '../lib/api';
import { fmtTime, label } from '../lib/format';

export const TICKER_LIMIT = 15;

export function latestEvents(tasks: Task[], limit = TICKER_LIMIT) {
  // Newest first. Events can share a time (an assign and a complete at the same slider time), so ties keep the
  // task's own stored order, later event first.
  return tasks
    .flatMap((t) => t.events.map((e, i) => ({ ...e, task: t, seq: i })))
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at) || (a.task === b.task ? b.seq - a.seq : 0))
    .slice(0, limit);
}

export function EventTicker({ tasks, error }: { tasks: Task[] | null; error: string | null }) {
  const events = tasks ? latestEvents(tasks) : [];
  return (
    <div className="relative flex items-center gap-4 overflow-hidden rounded border border-accent-cyan/15 bg-navy-panel p-2.5 font-mono text-[10px] text-slate-400">
      <span className="flex shrink-0 items-center gap-1 font-bold uppercase text-accent-cyan">
        <Layers className="h-3.5 w-3.5" /> Task events
      </span>
      <div className="relative flex-1 overflow-hidden whitespace-nowrap">
        {error ? <span className="text-danger-red">{error}</span>
          : !tasks ? <span>loading…</span>
          : !events.length ? <span>No task events up to this time.</span>
          : (
            <div className="animate-marquee inline-block space-x-12 pl-[100%]">
              {events.map((e, i) => (
                <span key={`${e.task.id}-${i}`} className="text-slate-300">
                  [{fmtTime(e.at)}] {label(e.task.kind)} → <span className="text-accent-cyan">{label(e.status)}</span>
                  {' '}· {e.actor} · {e.note}
                </span>
              ))}
            </div>
          )}
      </div>
    </div>
  );
}
