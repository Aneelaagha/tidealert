// One-shot pulse requests for the map: "a ring expands from this zone's marker". The map also pulses by itself when a zone's
// first task appears while the playhead is moving; this lets something else (the dev demo driver) ask for one. It carries
// a zone id only: where the ring is drawn comes from the zone's own task marker position, so nothing is invented.

type Listener = (zoneId: string) => void;
const listeners = new Set<Listener>();

export function onPulse(l: Listener): () => void {
  listeners.add(l);
  return () => { listeners.delete(l); };
}

export function pulseZone(zoneId: string): void {
  listeners.forEach((l) => l(zoneId));
}
