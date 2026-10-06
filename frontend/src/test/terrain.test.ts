import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { DEM_TILES, EXAGGERATION, MAX_EXAGGERATION, PITCH_3D, loadThreeD, saveThreeD, terrainSpec } from '../lib/terrain';

describe('3D terrain settings', () => {
  it('keeps the exaggeration at or below 1.5, whatever is asked for', () => {
    expect(EXAGGERATION).toBeLessThanOrEqual(MAX_EXAGGERATION);
    expect(terrainSpec().exaggeration).toBe(1.2);
    expect(terrainSpec(4).exaggeration).toBe(1.5);
  });
  it('uses the free terrarium tiles and a 55 degree pitch', () => {
    expect(DEM_TILES).toBe('https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png');
    expect(PITCH_3D).toBe(55);
  });
  it('is off when storage is missing or blocked, and does not throw', () => {
    expect(loadThreeD()).toBe(false); // vitest runs in node: no window, so the read is caught
    expect(() => saveThreeD(true)).not.toThrow();
  });
});

describe('the map stays honest in 3D', () => {
  const src = readFileSync(join(__dirname, '..', 'components', 'ZoneMap.tsx'), 'utf8');
  it('never extrudes zones or the flood and draws no water volume', () => {
    expect(src).not.toMatch(/fill-extrusion/);
    expect(src).not.toMatch(/extrusion|water volume|waterbody/i);
  });
  it('is off by default and forced flat while the demo runs', () => {
    expect(src).toMatch(/useState\(loadThreeD\)/);
    expect(src).toMatch(/const on3d = threeD && !flat/);
    expect(readFileSync(join(__dirname, '..', 'App.tsx'), 'utf8')).toMatch(/flat=\{demo\.active\}/);
  });
});
