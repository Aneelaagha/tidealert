import type { ReactNode } from 'react';

export type Tone = 'plain' | 'red' | 'green' | 'amber' | 'cyan';

const TONES: Record<Tone, string> = {
  plain: 'bg-white/5 text-slate-300', red: 'bg-red-950/50 text-red-300', green: 'bg-emerald-950/50 text-emerald-300',
  amber: 'bg-amber-950/50 text-amber-300', cyan: 'bg-cyan-950/50 text-accent-cyan',
};

export function Tag({ children, tone = 'plain' }: { children: ReactNode; tone?: Tone }) {
  return <span className={`mr-1 inline-block rounded px-1.5 py-px text-[10px] ${TONES[tone]}`}>{children}</span>;
}

export const Muted = ({ children }: { children: ReactNode }) => <span className="text-slate-500">{children}</span>;
