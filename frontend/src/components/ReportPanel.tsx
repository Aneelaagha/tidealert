// The after-action report for the run and time on screen, from GET /reports/after-action. Labelled with the run's
// mode first; every number is a count of stored rows, and the limits are on the page. The same content downloads as
// Markdown.

import { Download, FileText, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { type AfterAction, type Run, api } from '../lib/api';
import { label } from '../lib/format';
import { Time } from './ui';

const pairs = (o: Record<string, number>) => Object.entries(o).map(([k, v]) => `${label(k)} ${v.toLocaleString()}`).join(', ') || 'none';

export function download(r: AfterAction): void {
  const name = `after-action-${(r.run.event ?? r.run.mode).toLowerCase().replace(/\s+/g, '-')}-${r.as_of.slice(0, 16).replace(/[:T]/g, '-')}.md`;
  const url = URL.createObjectURL(new Blob([r.markdown], { type: 'text/markdown' }));
  const a = document.createElement('a');
  a.href = url; a.download = name; a.click();
  URL.revokeObjectURL(url);
}

export function ReportPanel({ run, at, onClose }: { run: Run; at: string | null; onClose: () => void }) {
  const [report, setReport] = useState<AfterAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    api.afterAction(run.id, at, ctl.signal).then(setReport).catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message); });
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => { ctl.abort(); window.removeEventListener('keydown', onKey); };
  }, [run.id, at, onClose]);

  const s = report?.summary;
  return (
    <div className="fixed inset-0 z-[60] flex justify-end bg-black/60" onClick={onClose} role="dialog" aria-modal="true" aria-label="After-action report">
      <div className="custom-scrollbar h-full w-full max-w-3xl overflow-y-auto border-l border-accent-cyan/25 bg-navy-panel p-5 text-sm text-slate-300" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-white"><FileText className="h-4 w-4 text-accent-cyan" /> After-action report</h2>
          <div className="flex items-center gap-2">
            {report && (
              <button type="button" onClick={() => download(report)}
                      className="flex cursor-pointer items-center gap-1 rounded border border-accent-cyan/50 bg-cyan-950/40 px-2 py-1 text-xs font-bold uppercase text-accent-cyan hover:bg-cyan-900/50">
                <Download className="h-3.5 w-3.5" /> Download .md
              </button>
            )}
            <button onClick={onClose} aria-label="Close" className="cursor-pointer rounded p-1 text-slate-400 hover:text-white"><X className="h-4 w-4" /></button>
          </div>
        </div>
        {error ? <p className="text-danger-red">{error}</p> : !report || !s ? <p className="text-slate-500">building the report…</p> : (
          <div className="space-y-4">
            <div>
              <h3 className="text-base font-bold text-white">{report.run.event ?? report.run.name}</h3>
              <p className="mt-1 rounded border border-warning-orange/40 bg-orange-950/20 p-2 font-semibold text-orange-200">{report.run.mode_label}</p>
              <p className="mt-1 text-xs text-slate-500">as of <Time t={report.as_of} />, on the run's clock · run <span className="font-mono">{report.run.name}</span></p>
            </div>

            <section>
              <h4 className="mb-1 text-xs font-bold uppercase tracking-wider text-accent-cyan">What was flagged</h4>
              <ul className="list-disc space-y-0.5 pl-5">
                <li>{s.cases.toLocaleString()} Cases in {s.flagged_zones.toLocaleString()} zones. By confidence: {pairs(s.cases_by_confidence)}.</li>
                <li><b className="text-danger-red">{s.zones_cut_off.zones.toLocaleString()} zones cut off</b> ({s.zones_cut_off.population.toLocaleString()} people recorded in them) · {s.zones_may_be_cut_off.zones.toLocaleString()} may be cut off · {s.zones_not_assessed.zones.toLocaleString()} not assessed.</li>
                <li>{s.tasks.toLocaleString()} tasks: {pairs(s.tasks_by_status)}.</li>
              </ul>
            </section>

            <section>
              <h4 className="mb-1 text-xs font-bold uppercase tracking-wider text-accent-cyan">Timeline</h4>
              <ul className="space-y-1">
                {report.timeline.length ? report.timeline.map((x, i) => (
                  <li key={i} className="flex gap-2"><span className="w-44 shrink-0 text-xs text-slate-500"><Time t={x.at} /></span><span>{x.text}</span></li>
                )) : <li className="text-slate-500">Nothing recorded.</li>}
              </ul>
            </section>

            <section>
              <h4 className="mb-1 text-xs font-bold uppercase tracking-wider text-accent-cyan">What was done</h4>
              {s.actions_taken === 0 ? <p>No assignments or other actions were recorded.</p>
                : <p>{s.actions_taken} actions by people or scripts (in the timeline){report.run.mode === 'mixed' || report.run.mode === 'scenario' ? ': scripted and synthetic, not real responders.' : '.'}</p>}
            </section>

            <section>
              <h4 className="mb-1 text-xs font-bold uppercase tracking-wider text-accent-cyan">Warnings on active tasks</h4>
              {report.warnings.total === 0 ? <p>None.</p> : (
                <>
                  <p>{report.warnings.total.toLocaleString()}: {pairs(report.warnings.by_code)}. First {report.warnings.examples.length}:</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5 text-slate-400">{report.warnings.examples.map((w, i) => <li key={i}><span className="font-mono">{w.zone}</span>: {w.text}</li>)}</ul>
                </>
              )}
            </section>

            <section>
              <h4 className="mb-1 text-xs font-bold uppercase tracking-wider text-accent-cyan">Caveats and limits</h4>
              <ul className="list-disc space-y-1 pl-5 text-slate-400">{[...report.caveats, ...report.limits].map((c) => <li key={c}>{c}</li>)}</ul>
            </section>
            <p className="text-xs text-slate-500">The download also lists every Case flagged, the sources at this time, and any needs and offers.</p>
          </div>
        )}
      </div>
    </div>
  );
}
