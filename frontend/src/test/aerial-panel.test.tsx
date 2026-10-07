import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { AerialPanel } from '../components/AerialPanel';
import type { AerialPriority, AerialZone } from '../lib/api';

const zone = (over: Partial<AerialZone> = {}): AerialZone => ({ rank: 1, zone_id: 'z1', zone_name: 'USGS-08074500 street block 01338ae7', cut_off_minutes: 252, silent_households: null,
  cell_coverage_assessed: false, score: null, reason_fragments: ['No dry route', 'Cut off 4h 12m', 'cell coverage: not assessed'], ...over });
const data = (over: Partial<AerialPriority> = {}): AerialPriority => ({ run_id: 'r', mode: 'replay', at: '', silence_active: false, available: true,
  note: 'Replay: ranked by cut-off duration. Silence inputs excluded — no opt-in registry existed in 2017.', caption: 'Ranking only. No live feed. No asset is tasked by this system.',
  empty: 'No zone meets the aerial-priority threshold at this time.', cut_off_zones: 152, shown: 1, zones: [zone()], reason: null, ...over });
const html = (d: AerialPriority | null, error: string | null = null) => renderToStaticMarkup(<AerialPanel data={d} error={error} selectedZoneId={null} onSelect={() => {}} />);

describe('the aerial priority panel', () => {
  it('on a replay shows the duration fragment, the replay line, no score and no silence label', () => {
    const h = html(data());
    expect(h).toContain('Aerial priority');
    expect(h).toContain('No dry route, Cut off 4h 12m, cell coverage: not assessed');
    expect(h).toContain('Aerial task recommended');
    expect(h).not.toContain('Silence inputs excluded'); // explanation lives in the write-up
    expect(h).not.toContain('score');
    expect(h).not.toContain('Silence inputs active');
  });
  it('off replay shows the silence label and the score', () => {
    const h = html(data({ mode: 'scenario', silence_active: true, note: 'Ranked by silent households. Cell coverage not assessed.', zones: [zone({ silent_households: 9, score: 9, reason_fragments: ['No dry route', 'Cut off 1h 00m', '9 silent households', 'cell coverage: not assessed'] })] }));
    expect(h).toContain('Silence inputs active');
    expect(h).not.toContain('Ranked by silent households');
    expect(h).toContain('9 silent households');
    expect(h).toContain('score');
  });
  it('says nothing meets the threshold when no zone is cut off, and ranks nothing else', () => {
    const h = html(data({ zones: [], shown: 0, cut_off_zones: 0 }));
    expect(h).toContain('No zone meets the aerial-priority threshold at this time.');
    expect(h).not.toContain('Aerial task recommended');
  });
  it('shows no feed, video, image or aircraft, and no footer caption', () => {
    for (const h of [html(data()), html(null), html(null, 'boom'), html(data({ zones: [] }))]) {
      expect(h).not.toContain('No asset is tasked by this system');
      expect(h).not.toMatch(/<(video|img|canvas|iframe)\b/);
    }
  });
});
