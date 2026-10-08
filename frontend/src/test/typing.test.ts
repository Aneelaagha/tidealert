import { afterEach, describe, expect, it, vi } from 'vitest';
import { chooseOption, delaysFor, seeded, setNativeValue, typeInto, untypable } from '../dev/typing';

// A stand-in for the browser's input: a prototype with a real `value` accessor, so the native-setter path is the one exercised.
class FakeInput {
  type = 'text'; disabled = false; readOnly = false; events: string[] = []; private v = '';
  get value() { return this.v; }
  set value(x: string) { this.v = x; }
  getBoundingClientRect() { return { width: 100, height: 20 }; }
  dispatchEvent(e: { type: string }) { this.events.push(`${e.type}:${this.v}`); return true; }
}
class FakeSelect extends FakeInput {
  options = [{ value: 'water' }, { value: 'food' }]; private sv = '';
  get value() { return this.sv; }
  set value(x: string) { this.sv = x; } // its own accessor, as a real <select> has
  dispatchEvent(e: { type: string }) { this.events.push(`${e.type}:${this.sv}`); return true; }
}
const stub = () => { vi.stubGlobal('HTMLInputElement', FakeInput); vi.stubGlobal('HTMLTextAreaElement', class {}); vi.stubGlobal('HTMLSelectElement', FakeSelect); };
afterEach(() => { vi.unstubAllGlobals(); });
const env = (log: string[] = [], cancelled = () => false) => ({ sleep: async () => {}, log: (l: string) => { log.push(l); }, cancelled });

describe('the seeded delay pattern', () => {
  it('is identical for the same text and seed, and different for another seed', () => {
    expect(delaysFor('Demo Operator', 2000)).toEqual(delaysFor('Demo Operator', 2000));
    expect(delaysFor('Demo Operator', 2000)).not.toEqual(delaysFor('Demo Operator', 2000, 7));
    const a = seeded(42), b = seeded(42);
    expect([a(), a(), a()]).toEqual([b(), b(), b()]);
  });
  it('has one pause per character, uneven, and sums to about the time asked for', () => {
    const d = delaysFor('Demo Operator', 2000);
    expect(d).toHaveLength(13);
    expect(new Set(d).size).toBeGreaterThan(3); // not a metronome
    expect(Math.abs(d.reduce((x, y) => x + y, 0) - 2000)).toBeLessThanOrEqual(13); // rounding only
    expect(Math.min(...d)).toBeGreaterThan(0);
  });
  it('is empty for no text', () => { expect(delaysFor('', 1000)).toEqual([]); });
});

describe('typing into a field', () => {
  it('fires an input event for every character through the native setter, and logs the final value', async () => {
    stub();
    const el = new FakeInput(); const log: string[] = [];
    const out = await typeInto(el as unknown as Element, '40', 1000, env(log), 'Quantity');
    expect(out).toBe('40');
    expect(el.events).toEqual(['input:', 'input:4', 'input:40']);
    expect(log).toEqual(['[scene2] typed into Quantity: "40"']);
  });
  it('starts from an empty field, as a person would', async () => {
    stub();
    const el = new FakeInput(); el.value = 'old';
    expect(await typeInto(el as unknown as Element, 'Test Donor', 500, env(), 'Donor')).toBe('Test Donor');
  });
  it('refuses a field a person would not type into: missing, disabled, read-only, hidden, a checkbox, a password', async () => {
    stub();
    expect(untypable(null)).toMatch(/not on the page/);
    const mk = (over: Partial<FakeInput>) => Object.assign(new FakeInput(), over) as unknown as Element;
    expect(untypable(mk({ disabled: true }))).toMatch(/disabled/);
    expect(untypable(mk({ readOnly: true }))).toMatch(/read-only/);
    expect(untypable(mk({ type: 'checkbox' }))).toMatch(/not typed into/);
    expect(untypable(mk({ type: 'password' }))).toMatch(/not typed into/);
    expect(untypable(Object.assign(mk({}), { getBoundingClientRect: () => ({ width: 0, height: 0 }) }))).toMatch(/not visible/);
    expect(untypable(mk({}))).toBeNull();
    await expect(typeInto(mk({ disabled: true }), 'x', 100, env(), 'Quantity')).rejects.toThrow(/Quantity: the field is disabled/);
  });
  it('stops when cancelled (Restart or a new play)', async () => {
    stub();
    const el = new FakeInput(); let n = 0;
    await typeInto(el as unknown as Element, 'abcdef', 600, env([], () => n++ >= 2), 'Field');
    expect(el.value.length).toBeLessThan(6);
  });
  it('chooses a select option through its native setter and a change event, or says the option is not there', () => {
    stub();
    const sel = new FakeSelect();
    expect(chooseOption(sel as unknown as HTMLSelectElement, 'water')).toBe(true);
    expect(sel.events).toEqual(['change:water']);
    expect(chooseOption(sel as unknown as HTMLSelectElement, 'gold')).toBe(false);
  });
  it('setNativeValue sets the value and fires one input event', () => {
    stub();
    const el = new FakeInput();
    setNativeValue(el as unknown as HTMLInputElement, 'x');
    expect(el.events).toEqual(['input:x']);
  });
});
