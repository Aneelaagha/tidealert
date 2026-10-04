// The legend: every value the API's vocabulary lists, with its color from COLORS. A value with no color is shown
// in UNSTYLED magenta and flagged, so the legend can't hide a state the map draws.

import type { ReactNode } from 'react';
import type { Vocabulary } from '../lib/api';
import { TASK_RADIUS, TASK_VERIFY_EDGE, UNSTYLED, colorOf } from '../lib/colors';
import { label } from '../lib/format';

const Unstyled = () => <span className="text-unstyled"> (unstyled value: no color mapped)</span>;

function Row({ swatch, children }: { swatch: ReactNode; children: ReactNode }) {
  return <div className="flex items-center gap-2 py-0.5">{swatch}<span>{children}</span></div>;
}

function Heading({ children }: { children: ReactNode }) {
  return <div className="mt-2.5 mb-0.5 text-[10px] uppercase tracking-wider text-slate-500 first:mt-0">{children}</div>;
}

export function Legend({ vocabulary }: { vocabulary: Vocabulary }) {
  return (
    <div className="font-mono text-[11px] text-slate-300">
      <Heading>Fill: zone risk level (unknown = not assessed, never shown as safe)</Heading>
      {vocabulary.risk_level.map((v) => {
        const c = colorOf('risk_level', v);
        return (
          <Row key={v} swatch={<span className="h-3.5 w-5 shrink-0 border border-white/20" style={{ background: c ?? UNSTYLED }} />}>
            {v}{c ? null : <Unstyled />}
          </Row>
        );
      })}

      <Heading>Outline: strongest Case confidence word in the zone</Heading>
      {vocabulary.confidence_word.map((v) => {
        const c = colorOf('confidence_word', v);
        return (
          <Row key={v} swatch={<span className="w-5 shrink-0 border-t-[3px]"
                                     style={{ borderTopColor: c ?? UNSTYLED, borderTopStyle: v === 'stale_verify' ? 'dashed' : 'solid' }} />}>
            {v}{c ? null : <Unstyled />}
          </Row>
        );
      })}
      <Row swatch={<span className="w-5 shrink-0 border-t border-slate-500" />}>thin grey outline: no Case</Row>
      <Row swatch={<span className="hatch-swatch h-3.5 w-5 shrink-0" />}>
        coverage gap active ({vocabulary.coverage_gap.join(', ')})
      </Row>

      <Heading>Marker: the zone's active tasks (fill = the most advanced status; all are listed in the zone panel)</Heading>
      {vocabulary.task_status.map((v) => {
        const c = colorOf('task_status', v);
        if (c === null) return <Row key={v} swatch={<span className="w-3.5 shrink-0" />}>{label(v)} <span className="text-slate-500">(closed: no marker)</span></Row>;
        return (
          <Row key={v} swatch={<span className="h-3.5 w-3.5 shrink-0 rounded-full border-[1.5px] border-slate-900" style={{ background: c ?? UNSTYLED }} />}>
            {label(v)}{c ? null : <Unstyled />}
          </Row>
        );
      })}
      <Row swatch={<span className="h-3.5 w-3.5 shrink-0 rounded-full bg-white" style={{ border: `3px solid ${TASK_VERIFY_EDGE}` }} />}>
        thick amber edge: at least one active task is flagged verify before dispatch
      </Row>
      <div className="flex flex-wrap items-center gap-2 py-0.5 text-slate-400">
        size = priority:
        {vocabulary.task_priority.map((p) => (
          <span key={p} className="inline-flex items-center gap-1">
            <span className="inline-block rounded-full border-[1.5px] border-slate-900 bg-white"
                  style={{ width: 2 * (TASK_RADIUS[p] ?? 7), height: 2 * (TASK_RADIUS[p] ?? 7) }} />{p}
          </span>
        ))}
      </div>

      <Row swatch={<span className="h-3.5 w-5 shrink-0" style={{ background: UNSTYLED }} />}>
        unstyled value: the API returned something with no color here
      </Row>
      <div className="mt-2 text-slate-500">
        Engines: {vocabulary.engine.map((e) => <span key={e} className="mr-1 rounded bg-white/5 px-1.5 py-px text-slate-300">{e}</span>)}
        (shown per zone in the panel)
      </div>
    </div>
  );
}
