// Data & ethics: how to read the map, where this run's data comes from, what is stored and shown about people,
// what the copilot may send where, and the gaps we know about. Facts come from GET /data-practices (computed from
// the code and the database), /runs and /map/freshness; each known gap shows the source it is pinned to.

import { ShieldCheck, X } from 'lucide-react';
import { type ReactNode, useEffect, useState } from 'react';
import { api, type DataPractices, type Freshness, type Run, type Vocabulary } from '../lib/api';
import { authenticationLine, consentLine, countLine, exposedLine, personalFieldsByOwner } from '../lib/ethics';
import { fmtAge, fmtTime, label } from '../lib/format';
import { MODE_MEANING } from '../lib/modes';


function Section({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="border-t border-navy-line pt-3">
      <h3 className="mb-2 text-[13px] font-bold uppercase tracking-wider text-accent-cyan">{n}. {title}</h3>
      <div className="space-y-1.5 font-sans text-sm leading-relaxed text-slate-300">{children}</div>
    </section>
  );
}

interface Props {
  run: Run | null;
  freshness: Freshness | null;
  vocabulary: Vocabulary | null;
  onClose: () => void;
}

export function EthicsPanel({ run, freshness, vocabulary, onClose }: Props) {
  const [dp, setDp] = useState<DataPractices | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    api.dataPractices(ctl.signal).then(setDp).catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message); });
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => { ctl.abort(); window.removeEventListener('keydown', onKey); };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[60] flex justify-end bg-black/60" onClick={onClose} role="dialog" aria-modal="true"
         aria-label="Data and ethics">
      <div className="custom-scrollbar h-full w-full max-w-2xl overflow-y-auto border-l border-accent-cyan/25 bg-navy-panel p-5"
           onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-white">
            <ShieldCheck className="h-4 w-4 text-accent-cyan" /> Data & ethics
          </h2>
          <button onClick={onClose} aria-label="Close" className="cursor-pointer rounded p-1 text-slate-400 hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mb-3 font-sans text-sm text-slate-400">
          What this system shows, where it comes from, and what it does with people's data. Statements about data come
          from the server's own report (<code className="text-slate-300">GET /data-practices</code>), computed from
          the code and the database, not written by hand.
        </p>
        {error && <p className="text-danger-red">{error}</p>}

        <div className="space-y-4">
          <Section n={1} title="Reading the map">
            <p><b>Fill is the zone's risk level</b>{vocabulary && <> ({vocabulary.risk_level.join(', ')})</>}. <b>Unknown means
              not assessed</b> and is never drawn as safe. Safe is shown only when an engine asserts it; no route lets
              anyone else set it.</p>
            <p><b>Outline is the strongest Case confidence word</b> (corroborated, single source, stale: verify). Confidence is
              given in words, not percentages, because the numbers behind it are not calibrated.</p>
            <p><b>The badge is the run's mode</b>, as registered, never inferred:</p>
            <ul className="list-disc pl-5">
              {(vocabulary?.mode ?? Object.keys(MODE_MEANING)).map((m) => (
                <li key={m}><b>{m}</b>: {MODE_MEANING[m] ?? 'no description'}</li>
              ))}
            </ul>
            <p><b>The slider is the run's own clock.</b> Nothing from after the slider time is shown. Hatching marks a
              coverage gap, where an engine could not assess the zone. <b>Magenta</b> means the server returned a value the
              page has no color for: it is flagged, never given a color that looks like a real state.</p>
          </Section>

          <Section n={2} title="This run's data">
            {run ? (
              <>
                <p><b>{run.description || run.name}</b> · {run.mode} · {run.window_start ? `${fmtTime(run.window_start)} to ${fmtTime(run.window_end)}` : 'live'}</p>
                <p>Sources this run reads:</p>
                <ul className="list-disc pl-5">
                  {run.sources.map((s) => {
                    const f = freshness?.sources.find((x) => x.name === s.name);
                    return (
                      <li key={s.name}>{s.name} <span className="text-slate-500">({s.category})</span>
                        {f && <> · {label(f.status)}{f.status !== 'no_data' && f.age_seconds != null ? `, last ${fmtAge(f.age_seconds)} before the slider time` : ''}</>}
                      </li>
                    );
                  })}
                  {!run.sources.length && <li className="text-slate-500">{freshness?.note ?? 'no recorded sources'}</li>}
                </ul>
                <ul className="list-disc pl-5 text-slate-400">{run.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
              </>
            ) : <p className="text-slate-500">loading…</p>}
          </Section>

          <Section n={3} title="People's data">
            {dp ? (
              <>
                <p>{countLine('households', dp.households)} {countLine('responders', dp.responders)}</p>
                <p>Stored per household: {dp.household_fields_stored.length} fields. Of those, these are personal:{' '}
                  <span className="text-[13px] text-slate-400">{personalFieldsByOwner(dp).household.join(', ')}</span>.
                  {personalFieldsByOwner(dp).other.length > 0 && <> Also personal, stored for responders:{' '}
                    <span className="text-[13px] text-slate-400">{personalFieldsByOwner(dp).other.join(', ')}</span>.</>}</p>
                <p><b>{exposedLine(dp)}</b></p>
                <p><b>{consentLine(dp)}</b> Nothing on this page or in the API implies a consent process exists.</p>
                <p>{authenticationLine(dp)}</p>
                <div className="rounded border border-warning-orange/30 bg-orange-950/20 p-2">
                  <p><b className="text-warning-orange">How this is checked, and what it can miss:</b> {dp.response_scan.limitation}</p>
                </div>
                <p className="text-slate-400">Only these routes can change data: <span className="text-[13px]">{dp.write_routes.join(' · ')}</span>.</p>
              </>
            ) : !error && <p className="text-slate-500">loading…</p>}
          </Section>

          <Section n={4} title="The copilot">
            {dp ? (
              <>
                <p><b>{dp.copilot.mode === 'model' ? `Model mode (${dp.copilot.model})` : 'Template mode'}</b>: {dp.copilot.reason}.</p>
                <p>It answers only from this run's data. In model mode the model never writes a value itself: it writes
                  placeholders that the server fills in, and an answer that states a status word, a number or copied text on
                  its own is thrown away in favour of a fixed template.</p>
                <p><b>{dp.copilot.external_model_rule}</b></p>
                <p className="text-slate-400">Its chat log is display only: each question is answered on its own.</p>
              </>
            ) : !error && <p className="text-slate-500">loading…</p>}
          </Section>

          <Section n={5} title="Known gaps">
            {dp ? (
              <ul className="space-y-2">
                {dp.known_gaps.map((g) => (
                  <li key={g.id} className="rounded border border-white/5 bg-navy-deep/60 p-2">
                    <p>{g.text}</p>
                    <p className="mt-0.5 text-xs text-slate-500">source: {g.source}</p>
                  </li>
                ))}
              </ul>
            ) : !error && <p className="text-slate-500">loading…</p>}
          </Section>
        </div>
      </div>
    </div>
  );
}
