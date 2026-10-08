// DEV ONLY (?dev=1, Scene 2). The typing effect: puts a string into a real input one character at a time, through the browser's own value setter
// and a real `input` event, so React's onChange runs exactly as it does for a person typing. The pauses between characters come from a fixed
// seed, so they look uneven but are identical on every run. It refuses any field a person would not type into. The final value is logged.

/** A small seeded generator (mulberry32): the same seed gives the same numbers every time. */
export function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** One pause per character, uneven (between 0.5x and 1.5x of the average) but summing to exactly `totalMs`. Identical for the same text and seed. */
export function delaysFor(text: string, totalMs: number, seed = 20170828): number[] {
  const n = [...text].length;
  if (n === 0) return [];
  const rnd = seeded(seed ^ n);
  const raw = Array.from({ length: n }, () => 0.5 + rnd());
  const sum = raw.reduce((a, b) => a + b, 0);
  return raw.map((r) => Math.round((r / sum) * totalMs));
}

const TEXT_TYPES = new Set(['text', 'search', 'tel', 'number', '']);

/** Why a field must not be typed into, or null when it may be: only a visible, enabled, writable text field qualifies. */
export function untypable(el: Element | null): string | null {
  if (!el) return 'the field is not on the page';
  if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) return 'not a text field';
  if (el instanceof HTMLInputElement && !TEXT_TYPES.has(el.type)) return `a ${el.type} field is not typed into`;
  if (el.disabled) return 'the field is disabled';
  if (el.readOnly) return 'the field is read-only';
  if (el.type === 'password') return 'a password field is never typed into';
  const r = el.getBoundingClientRect();
  if (r.width === 0 || r.height === 0) return 'the field is not visible';
  return null;
}

/** Set a field's value the way the browser does (so React's tracked value updates) and tell the page. */
export function setNativeValue(el: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

/** Choose an option in a <select> through its native setter and a real `change` event. Returns false when the option is not there. */
export function chooseOption(el: HTMLSelectElement, value: string): boolean {
  if (![...el.options].some((o) => o.value === value)) return false;
  Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!.call(el, value);
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
}

export interface TypeEnv { sleep(ms: number): Promise<void>; log(line: string): void; cancelled(): boolean }

/** Type `text` into `el` over `totalMs`. Resolves to the value the field ended with; throws with the reason when the field may not be typed into. */
export async function typeInto(el: Element | null, text: string, totalMs: number, env: TypeEnv, label = 'field', seed = 20170828): Promise<string> {
  const why = untypable(el);
  if (why) throw new Error(`${label}: ${why}`);
  const field = el as HTMLInputElement;
  setNativeValue(field, ''); // start empty, as a person would
  const chars = [...text];
  const delays = delaysFor(text, totalMs, seed);
  let typed = '';
  for (let i = 0; i < chars.length; i++) {
    if (env.cancelled()) break;
    await env.sleep(delays[i]);
    typed += chars[i];
    setNativeValue(field, typed);
  }
  env.log(`[scene2] typed into ${label}: ${JSON.stringify(field.value)}`);
  return field.value;
}
