import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { COUNTDOWN_S, PlayerClock, SPEEDS, TimelinePlayer, fmtClock, stepIndexAt } from '../dev/TimelinePlayer';

describe('the player clock', () => {
  it('stands still until played, runs in timeline seconds, and stops on pause', () => {
    let now = 1000;
    const c = new PlayerClock(() => now);
    now += 5000;
    expect(c.time()).toBe(0);
    c.play(); now += 2000;
    expect(c.time()).toBe(2);
    c.pause(); now += 9000;
    expect(c.time()).toBe(2);
    c.play(); now += 1000;
    expect(c.time()).toBe(3);
  });
  it('seeks, and changes speed without a jump in the time already elapsed', () => {
    let now = 0;
    const c = new PlayerClock(() => now);
    c.play(); now += 4000;
    c.setSpeed(0.5); expect(c.time()).toBe(4);
    now += 4000; expect(c.time()).toBe(6);
    c.setSpeed(1.5); now += 2000; expect(c.time()).toBe(9);
    c.seek(30); expect(c.time()).toBe(30);
    now += 1000; expect(c.time()).toBe(31.5);
    expect(SPEEDS).toEqual([0.5, 1, 1.5]);
  });
  it('stands still while a tool holds it for data, and only while playing', () => {
    let now = 0;
    const c = new PlayerClock(() => now);
    c.play(); now += 1000;
    c.hold(400); now += 400; // 400 ms of waiting for data
    expect(c.time()).toBeCloseTo(1, 6);
    c.pause(); c.hold(5000); now += 5000;
    expect(c.time()).toBeCloseTo(1, 6);
  });
  it('is the same every run: no randomness, the clock is the only input', () => {
    const run = () => { let now = 0; const c = new PlayerClock(() => now); c.play(); const out: number[] = []; for (let i = 0; i < 20; i++) { now += 250; out.push(c.time()); } return out; };
    expect(run()).toEqual(run());
  });
});

describe('steps and read-outs', () => {
  const steps = [{ at: 0, label: 'a' }, { at: 5, label: 'b' }, { at: 10, label: 'c' }];
  it('finds the step a time falls in, and none before the first', () => {
    expect([-1, 0, 4.9, 5, 9.99, 10, 99].map((t) => stepIndexAt(steps, t))).toEqual([-1, 0, 0, 1, 1, 2, 2]);
  });
  it('writes a clock as m:ss', () => { expect([fmtClock(0), fmtClock(84), fmtClock(61.9)]).toEqual(['0:00', '1:24', '1:01']); });
  it('counts down 3-2-1 before Play', () => { expect(COUNTDOWN_S).toBe(3); });
});

describe('the player panel', () => {
  const props = { title: 'Guided tour', steps: [{ at: 0, label: 'the-problem' }, { at: 5, label: 'who-it-is-for' }], duration: 84, clock: new PlayerClock(() => 0), status: 'ready' as const,
    line: { text: 'Read this line aloud.' }, message: null, countdown: null, onPlay: () => {}, onPause: () => {}, onRestart: () => {}, onSkip: () => {}, onSpeed: () => {} };
  const html = (over = {}) => renderToStaticMarkup(<TimelinePlayer {...props} {...over} />);
  it('has Play, Pause, Restart, a Skip menu, the three speeds, a progress bar and the narrator line', () => {
    const h = html();
    for (const word of ['Play', 'Pause', 'Restart', 'Skip to step', '0.5x', '1x', '1.5x', 'role="progressbar"', 'Read this line aloud.', '0:00 / 1:24']) expect(h).toContain(word);
  });
  it('lists every step in the Skip menu with its time', () => { expect(html()).toContain('2. who-it-is-for (0:05)'); });
  it('shows the countdown in place of the line, and a refusal in words', () => {
    const c = html({ status: 'countdown', countdown: 3 });
    expect(c).toContain('data-dev-countdown');
    expect(c).not.toContain('Read this line aloud.');
    const r = html({ status: 'refused', message: 'The guided tour starts only on the Harvey REPLAY.' });
    expect(r).toContain('role="alert"');
    expect(r).toContain('starts only on the Harvey REPLAY');
    expect(r).not.toContain('Read this line aloud.');
  });
  it('is fixed at the bottom right', () => { expect(html()).toContain('bottom-2 right-2'); });
});
