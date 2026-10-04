// Decorative sound only. The one tone is played by the header's "Sound test" button; nothing in the data triggers it
// and it announces nothing. Muted until the user turns sound on.

let ctx: AudioContext | null = null;
let muted = true;

function audio(): AudioContext | null {
  if (muted) return null;
  if (!ctx) ctx = new AudioContext();
  if (ctx.state === 'suspended') void ctx.resume();
  return ctx;
}

export const isMuted = () => muted;

export function setMuted(value: boolean) {
  muted = value;
}

/** A short two-oscillator tone. */
export function playTestTone() {
  const c = audio();
  if (!c) return;
  const a = c.createOscillator(), b = c.createOscillator(), gain = c.createGain();
  a.type = 'sawtooth';
  b.type = 'triangle';
  const t = c.currentTime;
  for (const [osc, f] of [[a, 110], [b, 220]] as const) {
    osc.frequency.setValueAtTime(f, t);
    osc.frequency.linearRampToValueAtTime(f * 1.18, t + 0.35);
    osc.frequency.linearRampToValueAtTime(f, t + 0.7);
    osc.connect(gain);
  }
  gain.gain.setValueAtTime(0.06, t);
  gain.gain.linearRampToValueAtTime(0.06, t + 0.5);
  gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.7);
  gain.connect(c.destination);
  a.start(); b.start();
  a.stop(t + 0.7); b.stop(t + 0.7);
}
