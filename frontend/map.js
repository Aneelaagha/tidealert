// TideAlert map: one run at a time, read as of a time on the run's clock.
//
// Everything drawn comes from the API (/runs, /map/zones, /map/freshness, /cases):
// zone shapes from the database geometry, the view from the run's extent, and
// fill/outline from each zone's own fields through data-driven styles. The one
// thing defined here is COLORS, the value -> color table. A value the API
// returns that is not in it is drawn in UNSTYLED magenta and flagged in the
// legend, never given a color that looks like a real state.

const UNSTYLED = "#ff00ff";
const COLORS = {
  // Fill. unknown is a neutral grey at low opacity: "not assessed", never green.
  risk_level: { unknown: "#9aa0a6", safe: "#2e7d32", elevated: "#f59e0b", extreme: "#c62828" },
  // Case outline. stale_verify is also dashed (separate layer).
  // stale_verify is brown, kept well away from the UNSTYLED magenta.
  confidence_word: { corroborated: "#0d47a1", single_source: "#1e88e5", stale_verify: "#795548" },
};
const GAP_COLOR = "#5f6b7a";
const TICK_MS = 15 * 60 * 1000; // the case matcher's sweep cadence

const el = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtTime = (iso) => iso ? new Date(iso).toISOString().replace("T", " ").slice(0, 16) + " UTC" : "—";
const fmtAge = (s) => s == null ? "—" : s < 3600 ? `${Math.round(s / 60)} min` : s < 172800 ? `${(s / 3600).toFixed(1)} h` : `${Math.round(s / 86400)} d`;

const state = { runs: [], vocabulary: null, run: null, ticks: [], at: null, zones: new Map(), gapReasons: [], request: 0 };

const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    sources: {
      osm: {
        type: "raster", tileSize: 256,
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      },
    },
    layers: [{ id: "osm", type: "raster", source: "osm" }],
  },
  center: [0, 0], zoom: 1,
});
map.addControl(new maplibregl.NavigationControl(), "top-left");

function matchColor(field) {
  const pairs = Object.entries(COLORS[field]).flat();
  return ["match", ["coalesce", ["get", field], "__null__"], ...pairs, UNSTYLED];
}

function hatchImage() {
  const size = 8, data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    if ((x + y) % size < 2) { const i = (y * size + x) * 4; data.set([95, 107, 122, 200], i); }
  }
  return { width: size, height: size, data };
}

function addLayers() {
  map.addSource("zones", { type: "geojson", data: { type: "FeatureCollection", features: [] }, promoteId: "zone_id" });
  map.addImage("hatch", hatchImage());
  map.addLayer({ id: "zone-fill", type: "fill", source: "zones", paint: {
    "fill-color": matchColor("risk_level"),
    "fill-opacity": ["case", ["==", ["get", "risk_level"], "unknown"], 0.12, 0.5],
  } });
  // Coverage gap: hatched and dashed, so a zone without real signal looks different instead of being left out.
  map.addLayer({ id: "zone-gap-hatch", type: "fill", source: "zones", filter: ["==", ["get", "coverage_gap_active"], true],
    paint: { "fill-pattern": "hatch", "fill-opacity": 0.55 } });
  map.addLayer({ id: "zone-edge", type: "line", source: "zones", paint: { "line-color": "#6e7781", "line-width": 0.4, "line-opacity": 0.6 } });
  map.addLayer({ id: "zone-gap-edge", type: "line", source: "zones", filter: ["==", ["get", "coverage_gap_active"], true],
    paint: { "line-color": GAP_COLOR, "line-width": 1, "line-dasharray": [2, 2] } });
  map.addLayer({ id: "case-outline", type: "line", source: "zones",
    filter: ["all", [">", ["get", "case_count"], 0], ["!=", ["get", "confidence_word"], "stale_verify"]],
    paint: { "line-color": matchColor("confidence_word"), "line-width": 3 } });
  map.addLayer({ id: "case-outline-stale", type: "line", source: "zones",
    filter: ["all", [">", ["get", "case_count"], 0], ["==", ["get", "confidence_word"], "stale_verify"]],
    paint: { "line-color": matchColor("confidence_word"), "line-width": 2.5, "line-dasharray": [1.5, 1] } });
  map.addLayer({ id: "zone-selected", type: "line", source: "zones", filter: ["==", ["get", "zone_id"], ""],
    paint: { "line-color": "#111", "line-width": 3 } });

  map.on("click", "zone-fill", (e) => selectZone(e.features[0].properties.zone_id));
  map.on("mouseenter", "zone-fill", () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", "zone-fill", () => { map.getCanvas().style.cursor = ""; });
}

async function api(path, params) {
  const url = new URL(path, window.location.origin);
  Object.entries(params || {}).forEach(([k, v]) => v != null && url.searchParams.set(k, v));
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
  return r.json();
}

// ---------------------------------------------------------------- legend
function legendRows(field, label) {
  const mapped = COLORS[field];
  const rows = state.vocabulary[field].map((v) => {
    const color = mapped[v];
    const sw = field === "confidence_word"
      ? `<span class="sw line" style="border-top-color:${color || UNSTYLED};${v === "stale_verify" ? "border-top-style:dashed" : ""}"></span>`
      : `<span class="sw" style="background:${color || UNSTYLED}"></span>`;
    return `<div class="legend-row">${sw}<span>${esc(v)}${color ? "" : ' <span class="warn">(unstyled value: no color mapped)</span>'}</span></div>`;
  }).join("");
  return `<div class="muted">${label}</div>${rows}`;
}

function renderLegend() {
  const v = state.vocabulary;
  el("legend").innerHTML = [
    legendRows("risk_level", "Fill: zone risk level (unknown = not assessed, never shown as safe)"),
    legendRows("confidence_word", "Outline: strongest Case confidence word in the zone"),
    `<div class="legend-row"><span class="sw" style="background:#fff"></span><span>thin grey outline: no Case</span></div>`,
    `<div class="legend-row"><span class="sw hatch"></span><span>coverage gap active (${v.coverage_gap.map(esc).join(", ")})</span></div>`,
    `<div class="legend-row"><span class="sw" style="background:${UNSTYLED}"></span><span>unstyled value: the API returned something with no color here</span></div>`,
    `<div class="muted" style="margin-top:6px">Engines: ${v.engine.map((e) => `<span class="tag">${esc(e)}</span>`).join("")} (shown per zone in the panel)</div>`,
  ].join("");
}

// ---------------------------------------------------------------- run, time
function setRun(run, atIso) {
  state.run = run;
  const badge = el("mode");
  badge.textContent = run.mode.toUpperCase();
  badge.className = `badge ${["replay", "scenario", "live"].includes(run.mode) ? run.mode : "unstyled"}`;
  badge.title = run.caveats.join("\n");

  const slider = el("slider");
  if (run.mode === "live" || !run.window_start) {
    state.ticks = [];
    slider.disabled = true; slider.max = 0;
  } else {
    const start = Date.parse(run.window_start), end = Date.parse(run.window_end);
    state.ticks = [];
    for (let t = start; t <= end; t += TICK_MS) state.ticks.push(new Date(t).toISOString());
    slider.disabled = false; slider.max = state.ticks.length - 1;
    const want = atIso ? state.ticks.indexOf(new Date(atIso).toISOString()) : -1;
    slider.value = want >= 0 ? want : state.ticks.length - 1;
  }
  if (run.extent) map.fitBounds([[run.extent[0], run.extent[1]], [run.extent[2], run.extent[3]]], { padding: 30, duration: 0 });
  el("detail").innerHTML = '<span class="muted">Click a zone to see its Cases and the evidence behind them.</span>';
  map.setFilter("zone-selected", ["==", ["get", "zone_id"], ""]);
  state.selected = null;
  loadAt();
}

function currentAt() { return state.ticks.length ? state.ticks[+el("slider").value] : null; }

async function loadAt() {
  const run = state.run, at = currentAt(), req = ++state.request;
  el("at-label").textContent = at ? fmtTime(at) : "now (live)";
  const params = new URLSearchParams({ run: run.id });
  if (at) params.set("at", at);
  history.replaceState(null, "", `?${params}`);
  el("status").textContent = "loading…";
  const t0 = performance.now();
  try {
    const [zones, fresh] = await Promise.all([
      api("/map/zones", { run_id: run.id, at }), api("/map/freshness", { run_id: run.id, at }),
    ]);
    if (req !== state.request) return; // a newer time was picked meanwhile
    state.at = zones.at;
    state.gapReasons = zones.gap_reasons;
    state.zones = new Map(zones.features.map((f) => [f.properties.zone_id, f.properties]));
    map.getSource("zones").setData(zones);
    renderBanner(fresh);
    const withCases = zones.features.filter((f) => f.properties.case_count > 0).length;
    const gaps = zones.features.filter((f) => f.properties.coverage_gap_active).length;
    el("status").textContent = `${zones.features.length.toLocaleString()} zones · ${withCases} with Cases · `
      + `${gaps.toLocaleString()} with an active coverage gap · ${((performance.now() - t0) / 1000).toFixed(1)} s`;
    if (state.selected) selectZone(state.selected);
  } catch (err) {
    if (req === state.request) el("status").innerHTML = `<span class="warn">${esc(err.message)}</span>`;
  }
}

function renderBanner(fresh) {
  const chips = fresh.sources.map((s) => {
    const age = s.status === "no_data" ? "no data yet" : `last ${fmtAge(s.age_seconds)} ago`;
    const rule = s.status === "event_driven" ? "event-driven, not judged" : `stale after ${fmtAge(s.stale_after_seconds)}${s.stale_after_overridden ? " (run override)" : ""}`;
    return `<span class="chip" title="${esc(rule)}"><span class="dot ${esc(s.status)}"></span>${esc(s.name)}: <b>${esc(s.status.replace("_", " "))}</b> (${esc(age)})</span>`;
  });
  if (fresh.note) chips.push(`<span class="muted">${esc(fresh.note)}</span>`);
  const caveats = state.run.caveats.map((c) => `<span class="caveat">${esc(c)}</span>`);
  el("banner").innerHTML = [`<b>Sources as of ${esc(fmtTime(fresh.at))}:</b>`, ...chips, ...caveats].join(" ");
}

// ---------------------------------------------------------------- zone detail
async function selectZone(zoneId) {
  state.selected = zoneId;
  map.setFilter("zone-selected", ["==", ["get", "zone_id"], zoneId]);
  const z = state.zones.get(zoneId);
  if (!z) return;
  const gaps = z.coverage_gaps.map((g) => `<li>${esc(g.kind)}${g.status ? ` — ${esc(g.status)}` : ""}: `
    + `${g.active ? "<b>active</b>" : `not yet (from ${esc(fmtTime(g.since))})`}`
    + `<div class="muted">${esc(state.gapReasons[g.reason_id])}</div></li>`).join("");
  const head = `<p><b>${esc(z.name)}</b> <span class="muted">${esc(z.region)}</span></p>
    <dl>
      <dt>Population</dt><dd>${esc(z.population)}</dd>
      <dt>Risk level</dt><dd>${esc(z.risk_level)}${z.risk_level_note ? ` <span class="muted">(${esc(z.risk_level_note)})</span>` : ""}</dd>
      <dt>Data confidence</dt><dd>${z.data_confidence == null ? '<span class="muted">not assessed</span>' : esc(z.data_confidence)}</dd>
      <dt>Cases</dt><dd>${z.case_count}${z.confidence_word ? ` · strongest: ${esc(z.confidence_word)}` : ""}</dd>
      <dt>Engines</dt><dd>${z.engines.length ? z.engines.map((e) => `<span class="tag">${esc(e)}</span>`).join("") : '<span class="muted">none</span>'}</dd>
    </dl>
    ${gaps ? `<div class="muted">Coverage gaps</div><ul>${gaps}</ul>` : ""}`;
  el("detail").innerHTML = head + (z.case_count ? '<p class="muted">loading Cases…</p>' : "");
  if (!z.case_count) return;
  const req = state.request;
  const body = await api("/cases", { run_id: state.run.id, zone_id: zoneId, at: state.at });
  if (req !== state.request || state.selected !== zoneId) return;
  el("detail").innerHTML = head + body.cases.map(renderCase).join("");
}

function renderCase(c) {
  const contribs = c.contributions.map((x) => `<div class="contrib">
      <span class="tag">${esc(x.engine)}</span><span class="tag ${esc(x.direction)}">${esc(x.direction)}</span>
      confidence ${x.engine_confidence.toFixed(2)} → ${x.effective_confidence.toFixed(2)} at this time
      ${x.independent_sources > 1 ? ` · ${x.independent_sources} sources` : ""}
      <div class="muted">first seen ${esc(fmtTime(x.first_observed_at))} · last confirmed ${esc(fmtTime(x.last_confirmed_at))}</div>
      <div>${esc(x.rule_fragment)}</div></div>`).join("");
  return `<div class="case">
    <p><b>${esc(c.confidence_word)}</b> · ${esc(c.status)} · opened ${esc(fmtTime(c.opened_at))}</p>
    <p>${esc(c.inference_sentence)}</p>
    <p class="muted">support ${c.support.toFixed(2)} · against ${c.contradiction.toFixed(2)} · fresh sources ${c.fresh_sources}</p>
    ${contribs}</div>`;
}

// ---------------------------------------------------------------- start
el("slider").addEventListener("input", () => { el("at-label").textContent = fmtTime(currentAt()); });
el("slider").addEventListener("change", loadAt);
el("run").addEventListener("change", () => setRun(state.runs.find((r) => r.id === el("run").value)));

// Start once the style is parsed, not on "load": "load" waits for the first rendered frame, which a hidden or
// background tab never draws, so data would not be fetched until the tab is shown.
async function start() {
  addLayers();
  try {
    const body = await api("/runs");
    state.runs = body.runs; state.vocabulary = body.vocabulary;
    renderLegend();
    if (!state.runs.length) { el("status").textContent = "No runs in the database."; return; }
    const span = (r) => r.window_start ? `${fmtTime(r.window_start).slice(0, 10)} → ${fmtTime(r.window_end).slice(0, 10)}` : "live";
    el("run").innerHTML = state.runs.map((r) => `<option value="${esc(r.id)}" title="${esc(r.name)}">${esc(r.description || r.name)}, ${esc(span(r))}</option>`).join("");
    const params = new URLSearchParams(location.search);
    const run = state.runs.find((r) => r.id === params.get("run")) || state.runs[0];
    el("run").value = run.id;
    setRun(run, params.get("at"));
  } catch (err) {
    el("status").innerHTML = `<span class="warn">${esc(err.message)}</span>`;
  }
}
if (map.isStyleLoaded()) start(); else map.once("style.load", start);
