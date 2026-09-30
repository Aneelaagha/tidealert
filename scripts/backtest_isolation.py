"""Backtest the isolation engine on Hurricane Harvey, White Oak Bayou (USGS 08074500 / NWS HGTT2).

Runs the engine twice over 2017-08-25 00:00 UTC .. 2017-09-03 05:00 UTC, hourly:

- OBS: stage from the USGS gauge (measured, gaps filled from USGS estimated
  discharge through the event rating curve).
- NWM: stage from NWM v2.1 retrospective discharge through the same curve,
  i.e. what a model-driven run would have produced.

Then compares against:

- NFIP claims (daily, by census block group) in the engine's zones, and
  Harris County overall. Claims have a date of loss but no time, so lead
  times are reported as a range: measured to the start and to the end of the
  claims-peak day (US Central, UTC-5 in August).
- Sentinel-1 change detection for two same-orbit pairs, against the FIM
  extent at the gauge stage at acquisition time.

Prerequisites: pull_nfip_claims.py, pull_gauge_nwm.py, pull_osm_roads.py,
pull_fim_library.py, load_zones.py, and the 3DEP DEM at backend/app/data/.

Usage (from the repo root):
    .venv/bin/python scripts/backtest_isolation.py
"""
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from geoalchemy2.shape import to_shape  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import NfipClaim, Zone  # noqa: E402
from app.services import isolation_engine as engine  # noqa: E402
from app.services import sentinel1, stage  # noqa: E402
from app.services.census import fetch_block_groups  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "app", "data")
FIM_PATH = os.path.join(DATA_DIR, "fim_hgtt2", "fim_extents.gpkg")
DEM_PATH = os.path.join(DATA_DIR, "dem_3dep_10m.tif")
REPORT_PATH = os.path.join(DATA_DIR, "backtest_isolation.json")

START = datetime(2017, 8, 25, 0, tzinfo=timezone.utc)
END = datetime(2017, 9, 3, 5, tzinfo=timezone.utc)
CENTRAL = timezone(timedelta(hours=-5), "CDT")
FT_TO_M = 0.3048

# NWS AHPS categories for HGTT2, ft.
CATEGORIES = {"action": 29.0, "minor (flood)": 32.0, "moderate": 33.5, "major": 36.0}

# Same-relative-orbit Sentinel-1 RTC pairs (pre, post).
S1_PAIRS = [
    ("S1A_IW_GRDH_1SDV_20170805T002619_20170805T002644_017781_01DCB4_rtc",
     "S1A_IW_GRDH_1SDV_20170829T002620_20170829T002645_018131_01E74D_rtc"),
    ("S1A_IW_GRDH_1SDV_20170824T122248_20170824T122318_018065_01E54E_rtc",
     "S1B_IW_GRDH_1SDV_20170830T122203_20170830T122232_007169_00CA2C_rtc"),
]
S1_DOMAIN_BUFFER_M = 200


def fmt(t: datetime | None) -> str:
    if t is None:
        return "never"
    return f"{t:%Y-%m-%d %H:%M} UTC ({t.astimezone(CENTRAL):%m-%d %H:%M} CDT)"


def lead_range(event: datetime, claims_day: date) -> tuple[float, float]:
    """Hours from event to the start and end of a (Central-time) claims day. Positive = event first."""
    day_start = datetime(claims_day.year, claims_day.month, claims_day.day, tzinfo=CENTRAL)
    to_start = (day_start - event).total_seconds() / 3600
    return to_start, to_start + 24


def first_crossing(series: stage.HourlyStage, threshold: float) -> datetime | None:
    return next((t for t, s in zip(series.times, series.stage_ft) if s >= threshold), None)


def claims_by_zone(db, zones: list[Zone]) -> tuple[dict[str, Counter], dict[str, int]]:
    """Daily claim counts per zone GEOID; claims with 2010 GEOIDs mapped to 2020 zones by overlap."""
    zone_geoids = {z.census_geoid for z in zones}
    zone_gdf = gpd.GeoDataFrame(
        {"geoid": [z.census_geoid for z in zones]},
        geometry=[to_shape(z.boundary) for z in zones],
        crs=4326,
    ).to_crs(engine.METRIC_CRS)

    # 2010 block groups around the zones that don't exist in the 2020 vintage.
    bgs_2010 = fetch_block_groups(2010, tuple(zone_gdf.to_crs(4326).total_bounds)).to_crs(engine.METRIC_CRS)
    remap = {}
    for bg in bgs_2010.itertuples():
        if bg.GEOID in zone_geoids:
            continue
        overlaps = zone_gdf.geometry.intersection(bg.geometry).area
        best = overlaps.idxmax()
        if overlaps[best] >= 0.5 * bg.geometry.area:
            remap[bg.GEOID] = zone_gdf.loc[best, "geoid"]

    rows = db.execute(
        select(NfipClaim.census_geoid, NfipClaim.date_of_loss, func.count())
        .where(NfipClaim.census_geoid.in_(zone_geoids | set(remap)))
        .group_by(NfipClaim.census_geoid, NfipClaim.date_of_loss)
    ).all()
    daily: dict[str, Counter] = defaultdict(Counter)
    via_2010 = Counter()
    for geoid, day, n in rows:
        target = geoid if geoid in zone_geoids else remap[geoid]
        daily[target][day] += n
        if geoid not in zone_geoids:
            via_2010[target] += n
    return daily, dict(via_2010)


def sentinel_check(fim: engine.FimLibrary, obs: stage.HourlyStage) -> list[dict]:
    domain = fim.extents[-1].buffer(S1_DOMAIN_BUFFER_M)
    bounds = domain.bounds
    results = []
    for pre_id, post_id in S1_PAIRS:
        pre = sentinel1.load_scene(pre_id, bounds)
        post = sentinel1.load_scene(post_id, bounds)
        water = sentinel1.new_water(pre, post)

        acquired = datetime.fromisoformat(post.acquired_at.replace("Z", "+00:00"))
        ts = np.array([t.timestamp() for t in obs.times])
        stage_ft = float(np.interp(acquired.timestamp(), ts, obs.stage_ft))
        nearest = int(np.argmin(np.abs(ts - acquired.timestamp())))
        layer = fim.layer_for_stage(stage_ft)

        shape = water.shape
        in_domain = rasterize([(domain, 1)], out_shape=shape, transform=post.transform, fill=0).astype(bool)
        fim_wet = (
            rasterize([(fim.extents[layer], 1)], out_shape=shape, transform=post.transform, fill=0).astype(bool)
            if layer >= 0 else np.zeros(shape, bool)
        )
        valid = in_domain & np.isfinite(pre.vv_db) & np.isfinite(post.vv_db)
        s1 = water & valid
        tp = int((s1 & fim_wet).sum())
        fp = int((s1 & ~fim_wet).sum())
        fn = int((~s1 & fim_wet & valid).sum())
        results.append({
            "pre": pre_id, "post": post_id, "orbit": f"{post.orbit_state} {post.relative_orbit}",
            "acquired_at": acquired,
            "gauge_stage_ft": stage_ft, "stage_provenance": obs.provenance[nearest],
            "fim_layer_ft": float(fim.stages_ft[layer]) if layer >= 0 else None,
            "fim_wet_km2": fim_wet[valid].sum() * 100 / 1e6,
            "s1_new_water_km2": s1.sum() * 100 / 1e6,
            "agree_km2": tp * 100 / 1e6,
            "fim_hit_rate": tp / (tp + fn) if tp + fn else None,
            "s1_inside_fim": tp / (tp + fp) if tp + fp else None,
            "csi": tp / (tp + fp + fn) if tp + fp + fn else None,
        })
    return results


def main() -> None:
    times = stage.hourly_times(START, END)
    with SessionLocal() as db:
        rating = stage.fit_event_rating(db)
        obs = stage.observed_stage(db, times, rating)
        nwm = stage.nwm_stage(db, times, rating)

        fim = engine.FimLibrary.load(FIM_PATH)
        road = engine.load_road_graph(db, fim)
        peak_wse_m = float(obs.stage_ft.max()) * FT_TO_M
        high_ground = engine.high_ground_nodes(road, fim, DEM_PATH, peak_wse_m)
        zone_nodes = engine.zone_nodes(db, road)
        runs = {name: engine.run_isolation(road, fim, series, zone_nodes, high_ground)
                for name, series in (("OBS", obs), ("NWM", nwm))}

        zones = list(zone_nodes)
        daily, via_2010 = claims_by_zone(db, zones)
        harris = Counter(dict(db.execute(
            select(NfipClaim.date_of_loss, func.count())
            .where(NfipClaim.county_fips == "48201")
            .group_by(NfipClaim.date_of_loss)
        ).all()))

        # Countdown to isolation as of the moment the gauge first reached action stage.
        action_at = first_crossing(obs, CATEGORIES["action"])
        engine.update_zone_countdowns(db, runs["OBS"], action_at)

    s1_results = sentinel_check(fim, obs)

    # ---------------------------------------------------------------- report
    print("=" * 78)
    print("STAGE DRIVER  (gauge datum 0 ft NAVD88)")
    n_rating = obs.provenance.count("rating")
    print(f"  OBS hours: {len(times)}  measured: {len(times) - n_rating}  "
          f"reconstructed from USGS estimated discharge: {n_rating}")
    for label, threshold in CATEGORIES.items():
        print(f"  {label:14s} {threshold:5.1f} ft  OBS {fmt(first_crossing(obs, threshold))}   "
              f"NWM {fmt(first_crossing(nwm, threshold))}")
    for name, series in (("OBS", obs), ("NWM", nwm)):
        i = int(np.argmax(series.stage_ft))
        print(f"  {name} peak {series.stage_ft[i]:.2f} ft at {fmt(series.times[i])} [{series.provenance[i]}]")

    print("\nROAD NETWORK")
    print(f"  segments in FIM reach that ever flood: {sum(np.isfinite(v) for v in road.edge_flood_layer.values())}; "
          f"bridges/tunnels in reach, exempt: {road.n_bridge_or_tunnel_exempt}; "
          f"high-ground nodes: {len(high_ground)} (>= {peak_wse_m + engine.HIGH_GROUND_FREEBOARD_M:.2f} m NAVD88)")

    for name, run in runs.items():
        i = int(np.argmax(run.stranded_node_count))
        print(f"\nISOLATION — {name}")
        print(f"  zones fully isolated: {sum(z.first_isolated_at is not None for z in run.zones)} of {len(run.zones)}")
        first_cut = next((t for t, a, b in zip(run.stage.times, run.stranded_node_count, run.submerged_node_count)
                          if a + b), None)
        first_stranded = next((t for t, a in zip(run.stage.times, run.stranded_node_count) if a), None)
        print(f"  first road node cut off: {fmt(first_cut)}")
        print(f"  first DRY node stranded: {fmt(first_stranded)}")
        print(f"  max stranded dry nodes: {run.stranded_node_count[i]} at {fmt(run.stage.times[i])} "
              f"(+{run.submerged_node_count[i]} submerged; {sum(len(v) for v in zone_nodes.values())} zone nodes)")
        print(f"  {'zone (2020 BG)':14s} {'nodes':>5s} {'isolated':>9s} {'first node cut':>34s} {'worst reach':>12s}")
        for z in sorted(run.zones, key=lambda z: (z.first_partial_cut_at is None, z.first_partial_cut_at or START)):
            print(f"  {z.census_geoid:14s} {z.n_nodes:5d} {fmt(z.first_isolated_at)[:9]:>9s} "
                  f"{fmt(z.first_partial_cut_at):>34s} {z.min_reachable_fraction:11.0%}")

    print("\nNFIP CLAIMS (date of loss, US Central)")
    days = [date(2017, 8, 25) + timedelta(days=d) for d in range(9)]
    zone_total = Counter()
    for c in daily.values():
        zone_total.update(c)
    print("  day        Harris   zones")
    for d in days:
        print(f"  {d:%m-%d}   {harris[d]:8d} {zone_total[d]:7d}")
    print(f"  claims in zones: {sum(zone_total.values())} ({sum(via_2010.values())} via 2010 GEOIDs mapped by overlap)")
    harris_peak = max(days, key=lambda d: harris[d])
    zone_peak = max(days, key=lambda d: zone_total[d])
    print(f"  claims peak day: Harris {harris_peak:%m-%d}, engine zones {zone_peak:%m-%d}")

    print("\nLEAD TIME (hours; + = signal before claims-peak day. Range = to start .. end of that day)")
    obs_run = runs["OBS"]
    signals = {
        "gauge reaches flood stage 32 ft (baseline)": first_crossing(obs, CATEGORIES["minor (flood)"]),
        "first road node cut off": next((t for t, a, b in zip(obs.times, obs_run.stranded_node_count,
                                                              obs_run.submerged_node_count) if a + b), None),
        "first dry node stranded": next((t for t, a in zip(obs.times, obs_run.stranded_node_count) if a), None),
        "any zone fully isolated": min((z.first_isolated_at for z in obs_run.zones if z.first_isolated_at), default=None),
    }
    for label, t in signals.items():
        if t is None:
            print(f"  {label:45s} never occurred -> no lead time")
            continue
        a, b = lead_range(t, zone_peak)
        c, d = lead_range(t, harris_peak)
        print(f"  {label:45s} {fmt(t)}  vs zones peak {a:+6.1f}..{b:+6.1f}  vs Harris peak {c:+6.1f}..{d:+6.1f}")
    print("  per zone (first node cut vs that zone's own claims-peak day):")
    for z in sorted(obs_run.zones, key=lambda z: z.census_geoid):
        claims = daily.get(z.census_geoid, Counter())
        if not claims or z.first_partial_cut_at is None:
            print(f"    {z.census_geoid}: claims={sum(claims.values()):4d}  "
                  f"{'no node cut' if z.first_partial_cut_at is None else 'no claims'}")
            continue
        peak = max(claims, key=claims.get)
        a, b = lead_range(z.first_partial_cut_at, peak)
        print(f"    {z.census_geoid}: claims={sum(claims.values()):4d} peak {peak:%m-%d} ({claims[peak]})  "
              f"lead {a:+6.1f}..{b:+6.1f} h")

    print("\nSENTINEL-1 vs FIM (within largest FIM extent + 200 m)")
    for r in s1_results:
        pct = lambda x: "n/a" if x is None else f"{x:.0%}"
        print(f"  {r['orbit']:14s} post {fmt(r['acquired_at'])}")
        print(f"     gauge {r['gauge_stage_ft']:.2f} ft [{r['stage_provenance']}] -> FIM layer {r['fim_layer_ft']} ft: "
              f"FIM wet {r['fim_wet_km2']:.3f} km2, S1 new water {r['s1_new_water_km2']:.3f} km2, "
              f"agree {r['agree_km2']:.3f} km2")
        print(f"     FIM area confirmed by S1: {pct(r['fim_hit_rate'])}; S1 water inside FIM: "
              f"{pct(r['s1_inside_fim'])}; CSI {pct(r['csi'])}")

    report = {
        "window_utc": [START.isoformat(), END.isoformat()],
        "stage_provenance_counts": dict(Counter(obs.provenance)),
        "runs": {
            name: {
                "zones": [
                    {"census_geoid": z.census_geoid, "n_nodes": z.n_nodes,
                     "first_isolated_at": z.first_isolated_at and z.first_isolated_at.isoformat(),
                     "first_partial_cut_at": z.first_partial_cut_at and z.first_partial_cut_at.isoformat(),
                     "min_reachable_fraction": z.min_reachable_fraction,
                     "min_reachable_at": z.min_reachable_at.isoformat()}
                    for z in run.zones
                ],
                "hourly": [
                    {"t": t.isoformat(), "stage_ft": float(s), "provenance": p, "fim_layer": int(layer),
                     "flooded_edges": f, "stranded_nodes": a, "submerged_nodes": b}
                    for t, s, p, layer, f, a, b in zip(run.stage.times, run.stage.stage_ft, run.stage.provenance,
                                                      run.layer_index, run.flooded_edge_count,
                                                      run.stranded_node_count, run.submerged_node_count)
                ],
            }
            for name, run in runs.items()
        },
        "claims_daily": {
            "harris": {d.isoformat(): harris[d] for d in days},
            "zones": {g: {d.isoformat(): n for d, n in sorted(c.items())} for g, c in daily.items()},
        },
        "sentinel1": [{**r, "acquired_at": r["acquired_at"].isoformat()} for r in s1_results],
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, default=float)
    print(f"\nWrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
