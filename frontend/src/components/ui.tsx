import type { ReactNode } from 'react';
import { fmtTime } from '../lib/format';

export type Tone = 'plain' | 'red' | 'green' | 'amber' | 'cyan';

const TONES: Record<Tone, string> = {
  plain: 'bg-white/5 text-slate-300', red: 'bg-red-950/50 text-red-300', green: 'bg-emerald-950/50 text-emerald-300',
  amber: 'bg-amber-950/50 text-amber-300', cyan: 'bg-cyan-950/50 text-accent-cyan',
};

export function Tag({ children, tone = 'plain' }: { children: ReactNode; tone?: Tone }) {
  return <span className={`mr-1 inline-block rounded px-1.5 py-px text-xs ${TONES[tone]}`}>{children}</span>;
}

export const Muted = ({ children }: { children: ReactNode }) => <span className="text-slate-500">{children}</span>;

/** Monospace is for IDs and times only: a time on the run's clock, or an identifier such as a zone's name. */
export const Mono = ({ children }: { children: ReactNode }) => <span className="font-mono">{children}</span>;
export const Time = ({ t }: { t: string | null | undefined }) => <span className="font-mono">{fmtTime(t)}</span>;
