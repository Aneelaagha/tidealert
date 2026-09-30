"""Build and execute notebooks/nfip_validation.ipynb (the spec's Proof Layer check against NFIP claims).

The notebook is generated from this file so its code is reviewable as plain
Python, then executed top to bottom with the repo's kernel so every number in
it comes from a real run against the database.

Prerequisites: the isolation pipeline and case matcher have run for the three
Harvey gauges (scripts/run_isolation_pipeline.py, scripts/run_case_matcher.py).

Usage (from the repo root):
    .venv/bin/python notebooks/build_nfip_validation.py
"""
import os

import nbformat
from nbclient import NotebookClient

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "nfip_validation.ipynb")

md = nbformat.v4.new_markdown_cell
code = nbformat.v4.new_code_cell

cells = [
    md("""# NFIP validation of isolation Cases: Hurricane Harvey 2017

Proof Layer check (spec §9): do the isolation engine's Cases (opened by the
case matcher's Harvey replay) point at the places that actually flooded, and
ahead of time? Compared with a static FEMA floodplain map that needs no
prediction at all.

**Definitions, fixed before looking at results:**

- **Unit:** 2020 census block groups (BGs) containing at least one of a
  basin's populated street blocks. NFIP claims are located by BG (2010-vintage
  GEOIDs mapped to 2020 BGs by majority overlap, as in the pipeline).
- **Claims window:** date of loss 2017-08-25 .. 2017-09-02, US Central.
- **Heavy-claims BG:** top 20% of a basin's BGs by NFIP claims per 100
  housing units (2020 census), with at least 5 claims.
- **Spike day:** a BG's peak date-of-loss day.
- **Engine flag:** a BG with at least one isolation Case (confirmed isolation)
  from the Harvey replay. Lead = hours from the BG's first Case to the start
  of its spike day (+ = Case first).
- **Static floodplain baseline (FEMA NFHL):** a BG is "at risk" if >= 10% of
  its populated street-block area lies in the 1%-annual-chance floodplain
  (SFHA, "100-year"). Variant: SFHA plus the 0.2%-annual-chance zone
  ("500-year").
- **Precision lower bound:** share of flagged BGs (and of Cases) with any
  NFIP claim at the time. This bounds "flooding happened there" from below
  (most homes had no flood insurance, so claims undercount). It is **not** a
  bound on isolation: no claim records whether a household was cut off."""),
    code("""import sys, os, json, math, logging, warnings
sys.path.insert(0, os.path.abspath("../backend")); sys.path.insert(0, os.path.abspath("../scripts"))
logging.disable(logging.WARNING); warnings.filterwarnings("ignore")
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta
import numpy as np, pandas as pd, geopandas as gpd, requests
from shapely.geometry import shape
from shapely.ops import unary_union
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Case, Zone
from app.services.census import fetch_block_groups
from app.services.river_driver import load_site_context, HARVEY_START, HARVEY_END
from run_isolation_pipeline import claims_by_block_group

pd.set_option("display.width", 200); pd.set_option("display.max_columns", 30)
BASINS = {"08074500": "White Oak", "08076000": "Greens", "08075770": "Hunting"}
CLAIM_START, CLAIM_END = date(2017, 8, 25), date(2017, 9, 2)
HEAVY_TOP_SHARE, HEAVY_MIN_CLAIMS = 0.20, 5
FLOODPLAIN_MIN_SHARE = 0.10
db = SessionLocal()"""),
    md("## 1. Block groups, claims, and Cases per basin"),
    code("""rows = []
contexts = {}
for site_id, name in BASINS.items():
    ctx = load_site_context(db, site_id)  # zones, road network, river-driver coverage
    contexts[site_id] = ctx
    tz = ctx.tz
    bgs = sorted({z.block_group_geoid for z in ctx.zones if z.block_group_geoid})
    bg_geo = fetch_block_groups(2020, tuple(ctx.site.basin.bounds))
    bg_geo = bg_geo[bg_geo.GEOID.isin(bgs)].set_index("GEOID")
    claims = claims_by_block_group(db, ctx.site, set(bgs), CLAIM_START, CLAIM_END)
    source = f"backtest:2017-08-25..2017-09-02:USGS-{site_id}"
    cases = list(db.scalars(select(Case).where(Case.source == source)))
    zone_bg = {z.id: z.block_group_geoid for z in ctx.zones}
    first_case = {}
    for c in cases:
        bg = zone_bg.get(c.zone_id)
        if bg and (bg not in first_case or c.opened_at < first_case[bg]):
            first_case[bg] = c.opened_at
    for bg in bgs:
        daily = claims.get(bg, Counter())
        n = sum(daily.values())
        peak = max(daily, key=daily.get) if n else None
        rows.append({
            "basin": name, "site": site_id, "bg": bg, "housing_units": int(bg_geo.loc[bg, "HU100"]) if bg in bg_geo.index else 0,
            "claims": n, "spike_day": peak, "first_case": first_case.get(bg),
            "spike_start": datetime(peak.year, peak.month, peak.day, tzinfo=tz) if peak else None,
        })
    print(f"{name}: {len(bgs)} BGs, {sum(sum(c.values()) for c in claims.values())} claims, {len(cases)} Cases in {len(first_case)} BGs")
df = pd.DataFrame(rows)
df["claims_per_100hu"] = np.where(df.housing_units > 0, 100 * df.claims / df.housing_units.clip(lower=1), np.nan)"""),
    md("## 2. Heavy-claims block groups"),
    code("""def mark_heavy(g):
    cut = g.claims_per_100hu.quantile(1 - HEAVY_TOP_SHARE)
    return (g.claims_per_100hu >= cut) & (g.claims >= HEAVY_MIN_CLAIMS)
df["heavy"] = df.groupby("basin", group_keys=False).apply(mark_heavy)
print(df.groupby("basin").agg(bgs=("bg", "size"), heavy=("heavy", "sum"), claims=("claims", "sum"),
                              heavy_claims=("claims", lambda s: s[df.loc[s.index, "heavy"]].sum())))
print("\\nHeavy-BG threshold (claims per 100 housing units):",
      df.groupby("basin").apply(lambda g: round(g.claims_per_100hu.quantile(1 - HEAVY_TOP_SHARE), 1)).to_dict())"""),
    md("""## 3. Recall at lead time: isolation Cases

For every heavy-claims BG: did it get an isolation Case before its spike day
started, during the spike day, after it, or never?"""),
    code("""def timing(r):
    if r.first_case is None or pd.isna(r.first_case): return "no case"
    if r.spike_start is None: return "case, no claims"
    lead_h = (r.spike_start - r.first_case).total_seconds() / 3600
    if lead_h > 0: return "before spike day"
    if lead_h > -24: return "on spike day"
    return "after spike day"
df["case_timing"] = df.apply(timing, axis=1)
df["lead_h"] = df.apply(lambda r: (r.spike_start - r.first_case).total_seconds() / 3600
                        if r.first_case is not None and not pd.isna(r.first_case) and r.spike_start is not None else np.nan, axis=1)
heavy = df[df.heavy]
order = ["before spike day", "on spike day", "after spike day", "case, no claims", "no case"]
recall = heavy.groupby("basin").case_timing.value_counts().unstack(fill_value=0).reindex(columns=order, fill_value=0)
recall.loc["ALL"] = recall.sum()
recall["heavy_bgs"] = recall[order].sum(axis=1)
recall["recall_any"] = (recall[order[:4]].sum(axis=1) / recall.heavy_bgs).round(3)
recall["recall_before"] = (recall["before spike day"] / recall.heavy_bgs).round(3)
print(recall)
hit = heavy[heavy.case_timing != "no case"]
print("\\nLead of first Case to the start of the spike day, hours (heavy BGs with a Case):")
print(hit[["basin", "bg", "claims", "spike_day", "first_case", "lead_h"]].sort_values("lead_h").to_string(index=False))"""),
    md("""### 3b. Recall where the engine could have spoken

Most of each basin is outside the river driver's coverage (the NWS map's
mapped extent, or the gauge's own reach for HAND), where the engine cannot
confirm isolation. Same recall, restricted to heavy BGs with at least one
street block bordered by a road the river driver covers."""),
    code("""covered_bgs = {}
for site_id, ctx in contexts.items():
    edge_covered = np.bincount(ctx.net.sample_edge, weights=ctx.net.sample_stage_known, minlength=len(ctx.net.u)) > 0
    bgs = set()
    for k, z in enumerate(ctx.zones):
        e = ctx.bounds.edges[ctx.bounds.ptr[k]:ctx.bounds.ptr[k + 1]]
        if len(e) and edge_covered[e].any() and z.block_group_geoid:
            bgs.add(z.block_group_geoid)
    covered_bgs[site_id] = bgs
df["covered"] = df.apply(lambda r: r.bg in covered_bgs[r.site], axis=1)
hc = df[df.heavy & df.covered]
rc = hc.groupby("basin").case_timing.value_counts().unstack(fill_value=0).reindex(columns=order, fill_value=0)
rc.loc["ALL"] = rc.sum()
rc["heavy_covered_bgs"] = rc[order].sum(axis=1)
rc["recall_any"] = (rc[order[:4]].sum(axis=1) / rc.heavy_covered_bgs).round(3)
rc["recall_before"] = (rc["before spike day"] / rc.heavy_covered_bgs).round(3)
print(rc)
print("\\nHeavy BGs inside river-driver coverage:", int(hc.shape[0]), "of", int(df.heavy.sum()))"""),
    md("""## 4. Static floodplain baseline (FEMA NFHL)

No prediction: which BGs were already mapped as floodplain? Fetched from
FEMA's National Flood Hazard Layer (current effective maps)."""),
    code("""NFHL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"
NFHL_CACHE = os.path.abspath("../backend/app/data/nfhl")
os.makedirs(NFHL_CACHE, exist_ok=True)
import time, hashlib
def nfhl_query(layer, bbox, fields, geometry=True):
    # All features of an NFHL layer in a bbox: paged, retried, cached on disk (FEMA's service is flaky).
    key = hashlib.sha1(json.dumps([layer, [round(b, 6) for b in bbox], fields, geometry]).encode()).hexdigest()[:16]
    path = os.path.join(NFHL_CACHE, f"layer{layer}-{key}.json")
    if os.path.exists(path):
        return json.load(open(path))
    feats, offset = [], 0
    env = json.dumps({"xmin": bbox[0], "ymin": bbox[1], "xmax": bbox[2], "ymax": bbox[3], "spatialReference": {"wkid": 4326}})
    while True:
        for attempt in range(6):
            try:
                r = requests.get(f"{NFHL}/{layer}/query", params={
                    "where": "1=1", "geometry": env, "geometryType": "esriGeometryEnvelope", "spatialRel": "esriSpatialRelIntersects",
                    "outFields": fields, "returnGeometry": str(geometry).lower(), "outSR": 4326, "f": "geojson",
                    "resultOffset": offset, "resultRecordCount": 1000}, timeout=300)
                page = r.json()["features"]
                break
            except (requests.RequestException, ValueError, KeyError):
                if attempt == 5: raise
                time.sleep(5 * (attempt + 1))
        feats += page
        if len(page) < 1000:
            break
        offset += len(page)
    with open(path + ".tmp", "w") as fh:
        json.dump(feats, fh)
    os.replace(path + ".tmp", path)
    return feats

floodplain = {}
panel_dates = Counter()
post_event_panels = {}
for site_id, ctx in contexts.items():
    bbox = tuple(ctx.site.basin.bounds)
    f = nfhl_query(28, bbox, "FLD_ZONE,ZONE_SUBTY,SFHA_TF")
    g = gpd.GeoDataFrame.from_features(f, crs=4326).to_crs(ctx.terrain.crs_epsg)
    sfha = g[g.SFHA_TF == "T"].geometry
    x500 = g[g.ZONE_SUBTY.fillna("").str.contains("0.2 PCT")].geometry
    floodplain[site_id] = {"sfha": unary_union(list(sfha.buffer(0))), "sfha_500": unary_union(list(sfha.buffer(0)) + list(x500.buffer(0)))}
    panels = gpd.GeoDataFrame.from_features(nfhl_query(3, bbox, "EFF_DATE,FIRM_PAN"), crs=4326).to_crs(ctx.terrain.crs_epsg)
    eff = pd.to_datetime(panels.EFF_DATE, unit="ms")
    panel_dates.update(eff.dt.date.astype(str))
    post_event_panels[site_id] = unary_union(list(panels[eff >= pd.Timestamp("2017-08-25")].geometry))
    print(f"{BASINS[site_id]}: {len(g)} flood hazard polygons, SFHA {floodplain[site_id]['sfha'].area / 1e6:.1f} km2, "
          f"SFHA+0.2% {floodplain[site_id]['sfha_500'].area / 1e6:.1f} km2")
print("FIRM panel effective dates (panels touching the basins):", dict(sorted(panel_dates.items())))"""),
    code("""share = {"sfha": {}, "sfha_500": {}}
on_post_event_panel = {}
for site_id, ctx in contexts.items():
    by_bg = defaultdict(list)
    for z, geom in zip(ctx.zones, ctx.zone_geoms):
        if z.block_group_geoid: by_bg[z.block_group_geoid].append(geom)
    for bg, geoms in by_bg.items():
        blocks = unary_union(geoms)
        for key in share:
            share[key][bg] = blocks.intersection(floodplain[site_id][key]).area / blocks.area if blocks.area else 0.0
        on_post_event_panel[bg] = blocks.intersects(post_event_panels[site_id])
df["fp100"] = df.bg.map(share["sfha"]).fillna(0) >= FLOODPLAIN_MIN_SHARE
df["fp500"] = df.bg.map(share["sfha_500"]).fillna(0) >= FLOODPLAIN_MIN_SHARE
df["engine"] = df.case_timing != "no case"
print("Floodplain-flagged BGs (100-yr) touching a FIRM panel made effective after Harvey (2017-08-25 or later):",
      int((df.fp100 & df.bg.map(on_post_event_panel).fillna(False)).sum()), "of", int(df.fp100.sum()))
df["engine_before"] = df.case_timing == "before spike day"

def score(flag, frame=None):
    frame = df if frame is None else frame
    flagged = frame[frame[flag]]
    heavy_n = int(frame.heavy.sum())
    return {"flagged_bgs": len(flagged),
            "recall_heavy": round(frame[frame.heavy][flag].sum() / heavy_n, 3) if heavy_n else np.nan,
            "precision_lb_any_claim": round((flagged.claims > 0).mean(), 3) if len(flagged) else np.nan,
            "share_flagged_heavy": round(flagged.heavy.mean(), 3) if len(flagged) else np.nan}

table = {}
for label, flag in [("isolation Case (any time)", "engine"), ("isolation Case before spike day", "engine_before"),
                    ("FEMA 100-yr floodplain (static)", "fp100"), ("FEMA 100+500-yr floodplain (static)", "fp500")]:
    table[label] = score(flag)
cmp_all = pd.DataFrame(table).T
cmp_all["base_rate_any_claim"] = round((df.claims > 0).mean(), 3)
cmp_all["base_rate_heavy"] = round(df.heavy.mean(), 3)
print("All basins, all BGs (%d BGs, %d heavy):" % (len(df), df.heavy.sum()))
print(cmp_all.to_string())
cov = df[df.covered]
table_cov = {label: score(flag, cov) for label, flag in [("isolation Case (any time)", "engine"),
            ("isolation Case before spike day", "engine_before"), ("FEMA 100-yr floodplain (static)", "fp100"),
            ("FEMA 100+500-yr floodplain (static)", "fp500")]}
print("\\nOnly BGs inside river-driver coverage (%d BGs, %d heavy):" % (len(cov), cov.heavy.sum()))
print(pd.DataFrame(table_cov).T.to_string())"""),
    md("""## 5. Case-level precision lower bound

For each Case: did its BG record any NFIP claim with a date of loss within a
day of the Case opening (Central time)? A lower bound on "flooding at that
place and time", not on isolation."""),
    code("""case_rows = []
for site_id, ctx in contexts.items():
    source = f"backtest:2017-08-25..2017-09-02:USGS-{site_id}"
    zone_bg = {z.id: z.block_group_geoid for z in ctx.zones}
    claims = claims_by_block_group(db, ctx.site, {b for b in zone_bg.values() if b}, CLAIM_START, CLAIM_END)
    for c in db.scalars(select(Case).where(Case.source == source)):
        day = c.opened_at.astimezone(ctx.tz).date()
        daily = claims.get(zone_bg.get(c.zone_id), Counter())
        near = sum(n for d, n in daily.items() if abs((d - day).days) <= 1)
        case_rows.append({"basin": BASINS[site_id], "case": str(c.id)[:8], "opened": c.opened_at.astimezone(ctx.tz),
                          "bg_claims_in_window": sum(daily.values()), "bg_claims_within_1_day": near})
cases_df = pd.DataFrame(case_rows)
summary = cases_df.groupby("basin").agg(cases=("case", "size"),
    with_claim_within_1_day=("bg_claims_within_1_day", lambda s: int((s > 0).sum())),
    with_any_claim_in_window=("bg_claims_in_window", lambda s: int((s > 0).sum())))
summary.loc["ALL"] = summary.sum()
summary["precision_lb_within_1_day"] = (summary.with_claim_within_1_day / summary.cases).round(3)
print(summary)"""),
    md("""## 6. Verdict

Computed from the tables above by fixed rules, not written by hand:
the engine "beats" the static baseline only if its recall of heavy-claims BGs
is higher *and* its flagged BGs are at least as likely to be heavy."""),
    code("""e, f100, f500 = table["isolation Case (any time)"], table["FEMA 100-yr floodplain (static)"], table["FEMA 100+500-yr floodplain (static)"]
eb = table["isolation Case before spike day"]
def beats(a, b):
    return a["recall_heavy"] > b["recall_heavy"] and a["share_flagged_heavy"] >= b["share_flagged_heavy"]
print(f"Heavy-claims BGs: {int(df.heavy.sum())} across {len(df)} BGs in three basins.")
print(f"Isolation Cases reach {e['recall_heavy']:.1%} of them at any time, {eb['recall_heavy']:.1%} before the BG's spike day.")
print(f"The static 100-yr floodplain flags {f100['recall_heavy']:.1%} of them before the storm (100+500-yr: {f500['recall_heavy']:.1%}).")
print(f"Engine beats the 100-yr floodplain baseline: {beats(e, f100)}; beats the 100+500-yr baseline: {beats(e, f500)}.")
print(f"Precision lower bounds (flagged BGs with any claim): engine {e['precision_lb_any_claim']:.1%}, "
      f"100-yr floodplain {f100['precision_lb_any_claim']:.1%}, all BGs {cmp_all['base_rate_any_claim'].iloc[0]:.1%}.")
ce, c100, c500 = (table_cov[k] for k in ("isolation Case (any time)", "FEMA 100-yr floodplain (static)",
                                         "FEMA 100+500-yr floodplain (static)"))
print(f"\\nInside river-driver coverage only ({len(cov)} BGs, {int(cov.heavy.sum())} heavy; a very small sample):")
print(f"  engine recall {ce['recall_heavy']:.1%} vs 100-yr {c100['recall_heavy']:.1%} vs 100+500-yr {c500['recall_heavy']:.1%}; "
      f"share of flagged BGs that are heavy: engine {ce['share_flagged_heavy']:.1%}, 100-yr {c100['share_flagged_heavy']:.1%}, "
      f"100+500-yr {c500['share_flagged_heavy']:.1%}")
print(f"  engine beats 100-yr: {beats(ce, c100)}; beats 100+500-yr: {beats(ce, c500)}")
on_day = int((heavy.case_timing == "on spike day").sum())
print(f"\\nTiming caveat: claims carry only a date. {on_day} heavy BGs got their first Case during their spike day, which "
      f"may or may not precede that day's damage; none got one before the day began.")"""),
]

nb = nbformat.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "tidealert", "display_name": "TideAlert (.venv)",
                                                                    "language": "python"}})
NotebookClient(nb, timeout=1800, kernel_name="tidealert", resources={"metadata": {"path": HERE}}).execute()
nbformat.write(nb, OUT)
print(f"Wrote {OUT}")
