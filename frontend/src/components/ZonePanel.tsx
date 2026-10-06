// The selected zone as of the slider time: its fields from /map/zones, then its Cases from /cases with their
// contributions and tasks (with each task's full event history).

import { useEffect, useState } from 'react';
import { api, type Case, type Needs, type Responder, type Run, type SupplyAccess, type Task, type ZoneProps } from '../lib/api';
import { fmtTime, label } from '../lib/format';
import { NeedsBlock } from './NeedsBlock';
import { SafetyNote } from './SafetyNote';
import { Muted, Tag, Time } from './ui';

const directionTone = (d: string) => (d === 'supports' ? 'red' : d === 'contradicts' ? 'green' : 'plain');

function responderName(responders: Map<string, Responder>, id: string | null): string | null {
  if (!id) return null;
  const r = responders.get(id);
  return r ? `${r.name}${r.synthetic ? ' (synthetic)' : ''}` : `responder ${id.slice(0, 8)}`;
}

function TaskBlock({ task, responders }: { task: Task; responders: Map<string, Responder> }) {
  const who = responderName(responders, task.assigned_responder_id);
  return (
    <div className="my-2 border-l-2 border-accent-cyan/60 bg-cyan-950/10 px-2 py-1.5">
      <p>
        <b>Task: {label(task.kind)}</b> · <Tag>{label(task.status)}</Tag><Tag>{task.priority}</Tag>
        {task.verify_before_dispatch && <Tag tone="amber">verify before dispatch</Tag>}
        {task.status === 'pending' && !task.verify_before_dispatch && <Muted>awaiting assignment</Muted>}
      </p>
      <p className="text-slate-500">{task.created_by_rule}{who ? ` · assigned to ${who}` : ''}</p>
      {task.active && <SafetyNote safety={task.safety} />}
      <details className="mt-1">
        <summary className="cursor-pointer text-slate-500">History ({task.events.length})</summary>
        <ul className="mt-1 space-y-1.5 pl-3">
          {task.events.map((e, i) => (
            <li key={i}>
              <Muted><Time t={e.at} /> · {e.actor}</Muted><br />
              <Tag>{label(e.status)}</Tag><Tag>{e.priority}</Tag>{e.verify_before_dispatch && <Tag tone="amber">verify</Tag>}
              {e.note}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function CaseBlock({ c, responders }: { c: Case; responders: Map<string, Responder> }) {
  return (
    <div className="my-2 rounded border border-white/10 bg-navy-deep/60 p-2.5">
      <p><b className="text-accent-cyan">{c.confidence_word}</b> · {label(c.status)} · opened <Time t={c.opened_at} /></p>
      <p className="my-1 font-sans text-slate-200">{c.inference_sentence}</p>
      <p className="text-slate-500">
        support {c.support.toFixed(2)} · against {c.contradiction.toFixed(2)} · fresh sources {c.fresh_sources}
      </p>
      {c.tasks.length ? c.tasks.map((t) => <TaskBlock key={t.id} task={t} responders={responders} />)
        : <p className="text-slate-500">No task at this time.</p>}
      <details className="mt-1">
        <summary className="cursor-pointer text-slate-500">Evidence ({c.contributions.length})</summary>
        {c.contributions.map((x, i) => (
          <div key={i} className="mt-1.5 border-t border-dashed border-white/10 pt-1.5">
            <Tag>{x.engine}</Tag><Tag tone={directionTone(x.direction)}>{x.direction}</Tag>
            confidence {x.engine_confidence.toFixed(2)} when last confirmed → {x.effective_confidence.toFixed(2)} at this time
            {x.independent_sources > 1 ? ` · ${x.independent_sources} sources` : ''}
            <div className="text-slate-500">first seen <Time t={x.first_observed_at} /> · last confirmed <Time t={x.last_confirmed_at} /></div>
            <div><Muted>Recorded when first observed: </Muted>{x.rule_fragment}</div>
          </div>
        ))}
      </details>
    </div>
  );
}

const supplyTone = (s: string) => (s === 'isolated' ? 'red' : s === 'possibly_isolated' ? 'amber' : s === 'reachable' ? 'green' : s === 'reconnected' ? 'cyan' : 'plain');

/** One zone's supply access: the state, since when, the engine's reason, and what the state does not mean. */
function SupplyAccessText({ supply, zoneId, at, error }: { supply: SupplyAccess | null; zoneId: string; at: string | null; error: string | null }) {
  if (error) return <span className="text-danger-red">{error}</span>;
  const z = supply && supply.at === at ? supply.zones[zoneId] : undefined;
  if (!supply || (at && supply.at !== at)) return <Muted>loading…</Muted>;
  if (!z) return <Muted>not in the answer</Muted>;
  return (
    <>
      <Tag tone={supplyTone(z.zone_access)}>{supply.labels[z.zone_access] ?? z.zone_access}</Tag>
      {z.since && <Muted>since <Time t={z.since} />{z.mechanism ? ` (${z.mechanism})` : ''}</Muted>}
      <div className="text-slate-500">{supply.reasons[z.reason_id].split('; confidence')[0]}</div>
      <details className="text-slate-500">
        <summary className="cursor-pointer">What this does not show</summary>
        {supply.does_not_show}
      </details>
    </>
  );
}

interface Props {
  run: Run;
  at: string | null;
  zone: ZoneProps | null;
  gapReasons: string[];
  responders: Map<string, Responder>;
  version: number; // bumped after a task action, so the zone's Cases are read again
  supply: SupplyAccess | null; // /map/supply-access for this run and time, or null while it loads
  supplyError: string | null;
  needs: Needs | null; // /needs for this run and time
  needsError: string | null;
  operator: string;
  onNeedsChanged: () => void;
}

export function ZonePanel({ run, at, zone, gapReasons, responders, version, supply, supplyError, needs, needsError, operator, onNeedsChanged }: Props) {
  const runId = run.id;
  const [cases, setCases] = useState<Case[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCases(null);
    setError(null);
    if (!zone || !zone.case_count) return;
    const ctl = new AbortController();
    api.cases(runId, zone.zone_id, at, ctl.signal)
      .then((body) => setCases(body.cases))
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message); });
    return () => ctl.abort();
  }, [runId, at, zone?.zone_id, zone?.case_count, version]);

  if (!zone) return <p className="text-[13px] text-slate-500">Click a zone to see its Cases and the evidence behind them.</p>;

  return (
    <div className="text-[13px] text-slate-300">
      <p className="text-xs"><b className="font-mono text-white">{zone.name}</b> <Muted>{zone.region}</Muted></p>
      <dl className="my-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
        <dt className="text-slate-500">Population</dt><dd>{zone.population ?? <Muted>not recorded</Muted>}</dd>
        <dt className="text-slate-500">Risk level</dt>
        <dd>{zone.risk_level}{zone.risk_level_note && <Muted> ({zone.risk_level_note})</Muted>}</dd>
        <dt className="text-slate-500">Data confidence</dt>
        <dd>{zone.data_confidence == null ? <Muted>not assessed</Muted> : zone.data_confidence}</dd>
        <dt className="text-slate-500">Cases</dt>
        <dd>{zone.case_count}{zone.confidence_word && ` · strongest: ${zone.confidence_word}`}</dd>
        <dt className="text-slate-500">Engines</dt>
        <dd>{zone.engines.length ? zone.engines.map((e) => <Tag key={e}>{e}</Tag>) : <Muted>none</Muted>}</dd>
        <dt className="text-slate-500">Supply access</dt>
        <dd><SupplyAccessText supply={supply} zoneId={zone.zone_id} at={at} error={supplyError} /></dd>
        <dt className="text-slate-500">Active tasks</dt>
        <dd>{zone.task_count
          ? `${zone.task_count} (most advanced: ${label(zone.task_status)}) · ${zone.task_awaiting} awaiting assignment · ${zone.task_flagged} flagged verify`
          : <Muted>none</Muted>}</dd>
      </dl>
      {zone.coverage_gaps.length > 0 && (
        <>
          <div className="text-slate-500">Coverage gaps</div>
          <ul className="mb-1 list-disc pl-4">
            {zone.coverage_gaps.map((g, i) => (
              <li key={i}>
                {g.kind}{g.status ? ` — ${g.status}` : ''}: {g.active ? <b>active</b> : `not yet (from ${fmtTime(g.since)})`}
                <div className="text-slate-500">{gapReasons[g.reason_id]}</div>
              </li>
            ))}
          </ul>
        </>
      )}
      <NeedsBlock run={run} zoneId={zone.zone_id} needs={needs} needsError={needsError} operator={operator} at={at} onChanged={onNeedsChanged} />
      {zone.case_count > 0 && (error ? <p className="text-danger-red">{error}</p>
        : cases ? cases.map((c) => <CaseBlock key={c.id} c={c} responders={responders} />)
        : <p className="text-slate-500">loading Cases…</p>)}
    </div>
  );
}
