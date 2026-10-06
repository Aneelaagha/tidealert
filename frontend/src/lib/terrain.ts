// 3D terrain for the map: a real elevation model draped under the existing layers, tilted camera, off by default.
// Elevation: AWS Terrain Tiles (Terrarium encoding), free and MapLibre-compatible. The backend's own DEM (the 3DEP file
// used for HAND) is a GeoTIFF the backend reads, not a tile service, so the page cannot load it without a new endpoint.
// There is NO water body here and the flood/zone fills are never extruded: they stay flat polygons on the terrain.

export const DEM_TILES = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';
export const EXAGGERATION = 1.2; // Houston is flat: anything above 1.5 would misrepresent it
export const MAX_EXAGGERATION = 1.5;
export const PITCH_3D = 55;
export const EASE_MS = 600;
export const STORAGE_KEY = 'tidealert.map3d';

export function loadThreeD(): boolean {
  try { return window.localStorage.getItem(STORAGE_KEY) === '1'; } catch { return false; }
}

export function saveThreeD(on: boolean): void {
  try { window.localStorage.setItem(STORAGE_KEY, on ? '1' : '0'); } catch { /* storage can be blocked: the toggle still works */ }
}

/** The terrain setting to hand to map.setTerrain, never above the cap. */
export function terrainSpec(exaggeration: number = EXAGGERATION): { source: string; exaggeration: number } {
  return { source: 'dem', exaggeration: Math.min(exaggeration, MAX_EXAGGERATION) };
}
