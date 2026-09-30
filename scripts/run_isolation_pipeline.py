"""Run the isolation pipeline and backtest for one USGS gauge. The gauge ID is the only site input.

Everything site-specific is derived:

    COMID, location          NLDI crosswalk
    study area               NLDI upstream drainage basin
    flood thresholds         NWS NWPS categories (logged percentile fallback)
    gauge datum, time zone   USGS monitoring location, NWS NWPS
    river flooding           NWS flood-map library where NWS publishes one;
                             otherwise HAND on USGS 3DEP + NHDPlus (lower confidence)
    roads                    OSM inside the basin, as of the day before the event
    zones                    OSM street blocks with 2020 census population
    rainfall                 AORC over the basin (input data only; see below)
    claims                   OpenFEMA NFIP claims for the zones' counties
    validation               HAND vs NWS flood map (every run), Sentinel-1 pairs

Isolation output is river-driven only, with bounded reachability for roads
whose flooding is unknown (reachable / isolated / possibly isolated). The
rain (ponding) driver is evaluated against Sentinel-1 on every run but is
not yet validated, so it produces no isolation output: see
docs/algorithms/isolation-engine.md.

The event window defaults to Hurricane Harvey (2017-08-25 .. 2017-09-02
US Central). It describes the event, not the site.

Slow downloads are cached under backend/app/data/usgs-<site>/. The report is
printed and written to backend/app/data/usgs-<site>/backtest.json.

Usage (from the repo root):
    .venv/bin/python scripts/run_isolation_pipeline.py 08074500
"""
import argparse
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

import geopandas as gpd
import numpy as np
from rasterio.warp import Resampling, reproject

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from geoalchemy2.shape import to_shape  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import NfipClaim, Zone  # noqa: E402
from app.services import isolation_engine as engine  # noqa: E402
from app.services import sentinel1  # noqa: E402
from app.services.census import fetch_block_groups  # noqa: E402
from app.services.fim_library import fetch_fim_extents, iou  # noqa: E402
from app.services.gauge_site import GaugeSite, resolve_gauge  # noqa: E402
from app.services.ingest import ingest_gauge, ingest_rainfall, ingest_roads  # noqa: E402
from app.services.nfip import pull_claims  # noqa: E402
from app.services.river_driver import (  # noqa: E402
    build_river_driver, depth_over_channel, local_zone, river_flood_mask,
)
from app.services.rainfall import (  # noqa: E402
    RESIDUAL_DRAIN_BRACKET, RESIDUAL_DRAIN_FRACTION, aorc_rainfall, drainage_capacity_mm_hr, ponding_levels,
)
from app.services.stage import StageSeries, fit_event_rating, observed_stage, timesteps  # noqa: E402
from app.services.street_blocks import basin_segments, generate_zones  # noqa: E402
from app.services.terrain import Terrain, build_terrain, download_dem  # noqa: E402

log = logging.getLogger("pipeline")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "app", "data")
DEFAULT_START = datetime(2017, 8, 25, 5, tzinfo=timezone.utc)  # 2017-08-25 00:00 CDT
DEFAULT_END = datetime(2017, 9, 3, 5, tzinfo=timezone.utc)  # 2017-09-03 00:00 CDT
# The rain driver's parameters were fit on this gauge; every other gauge is a held-out check.
RAIN_FIT_SITE = "08076000"


def utc_arg(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def rain_ponding_mask(terrain: Terrain, levels: np.ndarray, catchments: np.ndarray, river_wet: np.ndarray) -> np.ndarray:
    """Cells the rain driver ponds that the river driver does not already flood: closed depressions
    (>= engine.DEPRESSION_MIN_M) below their catchment's ponding level."""
    pos = np.searchsorted(catchments, terrain.catchment_comid)
    valid = (terrain.catchment_comid > 0) & (pos < len(catchments))
    valid &= catchments[np.minimum(pos, len(catchments) - 1)] == terrain.catchment_comid
    level = np.where(valid, levels[np.minimum(pos, len(catchments) - 1)], -np.inf)
    with np.errstate(invalid="ignore"):
        below = terrain.hand_network <= level
    return below & (terrain.depression_depth >= engine.DEPRESSION_MIN_M) & terrain.in_basin & ~river_wet


def claims_by_block_group(db, site: GaugeSite, block_groups: set[str], start: date, end: date) -> dict[str, Counter]:
    """Daily claims per 2020 block group; claims with 2010 GEOIDs mapped to the 2020 block group they mostly overlap."""
    bbox = tuple(site.basin.bounds)
    bg2020 = fetch_block_groups(2020, bbox)
    bg2020 = bg2020[bg2020.GEOID.isin(block_groups)].to_crs(3857)
    bg2010 = fetch_block_groups(2010, bbox).to_crs(3857)
    remap = {}
    for bg in bg2010.itertuples():
        if bg.GEOID in block_groups or bg2020.empty:
            continue
        overlap = bg2020.geometry.intersection(bg.geometry).area
        best = overlap.idxmax()
        if overlap[best] >= 0.5 * bg.geometry.area:
            remap[bg.GEOID] = bg2020.loc[best, "GEOID"]
    rows = db.execute(
        select(NfipClaim.census_geoid, NfipClaim.date_of_loss, func.count())
        .where(NfipClaim.census_geoid.in_(block_groups | set(remap)))
        .where(NfipClaim.date_of_loss.between(start, end))
        .group_by(NfipClaim.census_geoid, NfipClaim.date_of_loss)
    ).all()
    daily: dict[str, Counter] = defaultdict(Counter)
    for geoid, day, n in rows:
        daily[geoid if geoid in block_groups else remap[geoid]][day] += n
    return daily


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site", help="USGS site number, e.g. 08074500")
    parser.add_argument("--start", type=utc_arg, default=DEFAULT_START, help="event start (ISO, UTC)")
    parser.add_argument("--end", type=utc_arg, default=DEFAULT_END, help="event end (ISO, UTC)")
    parser.add_argument("--step-minutes", type=int, default=15)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    start, end = args.start, args.end
    osm_date = (start - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")

    site = resolve_gauge(args.site)
    tz = local_zone(site)
    cache = os.path.join(DATA_DIR, f"usgs-{site.site_id}")
    os.makedirs(cache, exist_ok=True)

    def fmt(t):
        return "never" if t is None else f"{t:%Y-%m-%d %H:%M} UTC ({t.astimezone(tz):%m-%d %H:%M %Z})"

    report: dict = {"site": site.site_id, "name": site.name, "comid": site.comid, "window_utc": [str(start), str(end)]}

    with SessionLocal() as db:
        gauge_counts = ingest_gauge(db, site, start, end)

        dem_path = os.path.join(cache, "dem_3dep.tif")
        if not os.path.exists(dem_path):
            download_dem(site, dem_path)
        terrain_path = os.path.join(cache, "terrain.npz")
        if os.path.exists(terrain_path):
            terrain = Terrain.load(terrain_path)
        else:
            terrain = build_terrain(site, dem_path)
            terrain.save(terrain_path)

        roads_path = os.path.join(cache, f"roads-{osm_date[:10]}.json")
        if not os.path.exists(roads_path):
            # Write-then-rename so an interrupted load never leaves a partial cache file behind.
            loaded = ingest_roads(db, site, osm_date)
            with open(roads_path + ".tmp", "w") as f:
                json.dump(loaded, f)
            os.replace(roads_path + ".tmp", roads_path)
        with open(roads_path) as f:
            road_counts = json.load(f)
        log.info("Roads: %d segments from OSM as of %s, fetched from Overpass at %s", road_counts["segments"],
                 road_counts["osm_date"], road_counts["fetched_at"])

        generate_zones(db, site, terrain.crs_epsg, road_counts["edge_ids"])
        zones = list(db.scalars(select(Zone).where(Zone.region == site.region).order_by(Zone.name)))
        zone_geoms = gpd.GeoSeries([to_shape(z.boundary) for z in zones], crs=4326).to_crs(terrain.crs_epsg)

        # Rainfall is ingested as input data; the rain driver produces no isolation output until validated.
        rain = aorc_rainfall(terrain, start - timedelta(hours=1), end)
        ingest_rainfall(db, site, rain)

        times = timesteps(start, end, timedelta(minutes=args.step_minutes))
        rating = fit_event_rating(db, site.site_id)
        stage = observed_stage(db, site.site_id, times, rating)
        depth, depth_method = depth_over_channel(site, stage, terrain)

        fim = fetch_fim_extents(site.fim_mapserver_url).to_crs(terrain.crs_epsg) if site.fim_mapserver_url else None
        river = build_river_driver(site, terrain, stage, depth, fim)
        log.info("USGS %s: river driver %s [%s]; covers %s", site.site_id, river.method, river.confidence,
                 river.coverage_desc)

        segments = basin_segments(db, site, terrain.crs_epsg, road_counts["edge_ids"])
        net = engine.build_network(segments, terrain, np.array([], dtype=np.int64), river.threshold, river.known)

        # Standing check: at the first timestep the river must be at base flow and nothing may flood.
        if stage.stage_ft[0] >= site.thresholds.minor_ft:
            raise engine.BaseFlowFloodingError(
                f"Event window starts at {fmt(times[0])} with stage {stage.stage_ft[0]:.2f} ft, already at/above "
                f"minor flood stage {site.thresholds.minor_ft:.2f} ft; the window must start at base flow")
        engine.assert_dry_at_base_flow(net, float(river.level[0]), None, fmt(times[0]))

        bounds = engine.zone_boundaries(zones, zone_geoms, net)
        # Pessimistic bound: roads with unknown flooding are impassable while the gauge is at/above minor stage.
        unknown_blocked = stage.stage_ft >= site.thresholds.minor_ft
        bounded = engine.run_bounded(net, bounds, times, river.level, unknown_blocked)
        for name, r in (("optimistic", bounded.optimistic), ("pessimistic", bounded.pessimistic)):
            if r.isolated_zones[0]:
                raise engine.BaseFlowFloodingError(
                    f"Base-flow check failed at {fmt(times[0])}: {r.isolated_zones[0]} evaluated zones are "
                    f"isolated in the {name} run")
        log.info("Base-flow check passed at %s: stage %.2f ft, 0 segments flooded, 0 evaluated zones isolated "
                 "(optimistic and pessimistic)", fmt(times[0]), stage.stage_ft[0])
        run = bounded.optimistic  # known flooding only
        alarm = stage.first_crossing(site.thresholds.minor_ft)
        engine.update_zone_countdowns(db, bounded, alarm or times[0], site.site_id, river.caveat)

        # Rain driver: evaluated against Sentinel-1 below, never used for isolation (engine gate).
        capacity = drainage_capacity_mm_hr(site)
        rain_ponding = {frac: ponding_levels(terrain, rain, times, capacity, unknown_blocked, frac)
                        for frac in (RESIDUAL_DRAIN_FRACTION, *RESIDUAL_DRAIN_BRACKET)}

        block_groups = {z.block_group_geoid for z in zones if z.block_group_geoid}
        counties = sorted({bg[:5] for bg in block_groups})
        claim_start = start.astimezone(tz).date()
        claim_end = (end - timedelta(seconds=1)).astimezone(tz).date()
        pull_claims(db, counties, claim_start, claim_end)
        claims = claims_by_block_group(db, site, block_groups, claim_start, claim_end)

    # ------------------------------------------------------------------ report
    th = site.thresholds
    print("=" * 88)
    print(f"USGS {site.site_id}  {site.name}")
    print(f"  COMID {site.comid} (NLDI) | NWS {site.nws_lid or 'none'} | basin "
          f"{terrain.in_basin.sum() * terrain.cell_area_m2 / 1e6:.1f} km2 (NLDI) | DEM "
          f"{abs(terrain.transform.a):.1f} m EPSG:{terrain.crs_epsg}")
    for label, value in (("action", th.action_ft), ("minor", th.minor_ft), ("moderate", th.moderate_ft),
                         ("major", th.major_ft)):
        prov = th.provenance.get(label, "not published")
        if prov.startswith("fallback"):
            prov = f"*** FALLBACK, NOT AN NWS THRESHOLD: {prov.removeprefix('fallback: ')} ***"
        crossed = stage.first_crossing(value) if value is not None else None
        print(f"  {label:8s} {'' if value is None else f'{value:6.2f} ft'}  [{prov}]  first reached {fmt(crossed)}")
    n_rating = stage.provenance.count("rating")
    peak_i = int(np.argmax(stage.stage_ft))
    print(f"  stage steps: {len(times)} ({len(times) - n_rating} measured, {n_rating} from rating curve on "
          f"USGS discharge incl. {gauge_counts['estimated']} ESTIMATED values)")
    print(f"  peak {stage.stage_ft[peak_i]:.2f} ft at {fmt(times[peak_i])} [{stage.provenance[peak_i]}]; "
          f"depth over channel {depth[peak_i]:.2f} m via {depth_method}")
    by_day = defaultdict(list)
    for t, v in zip(rain.times, rain.basin_mean_mm_hr):
        by_day[(t - timedelta(hours=1)).astimezone(tz).date()].append(float(v))
    print(f"  rainfall input (AORC; basin-mean total {rain.basin_mean_mm_hr.sum():.0f} mm) by local day, mm "
          f"(max mm/h): " + "  ".join(f"{d:%m-%d} {sum(v):.0f} ({max(v):.1f})" for d, v in sorted(by_day.items())))
    print(f"  base-flow check passed at {fmt(times[0])}")
    report["rainfall_daily_mm"] = {str(d): sum(v) for d, v in sorted(by_day.items())}
    report["depth_method"] = depth_method
    report["thresholds"] = {"values": {"action": th.action_ft, "minor": th.minor_ft, "moderate": th.moderate_ft,
                                       "major": th.major_ft}, "provenance": th.provenance}

    print(f"\nRIVER DRIVER: {river.method}  [{river.confidence}]")
    print(f"  coverage: {river.coverage_desc}")
    if river.caveat:
        print(f"  *** {river.caveat} ***")
    report["river_driver"] = {"method": river.method, "confidence": river.confidence, "caveat": river.caveat,
                              "coverage": river.coverage_desc}

    if fim is not None:
        # Ongoing validation, every run: HAND vs the NWS map inside the map's coverage.
        domain = river.known
        fim_wet_at = lambda s: domain & (river.threshold <= s)
        with np.errstate(invalid="ignore"):
            hand_wet_at = lambda d: domain & (terrain.hand_mainstem <= d)
        stage_depth = lambda s: depth_over_channel(site, StageSeries([times[0]], np.array([s]), ["fim"]), terrain)[0][0]
        per_stage = {float(s): iou(hand_wet_at(stage_depth(s)), fim_wet_at(s)) for s in sorted(fim.stage_ft)}
        flooding = [i for i in range(len(times)) if stage.stage_ft[i] >= th.minor_ft and np.isfinite(river.level[i])]
        per_step = [iou(hand_wet_at(depth[i]), fim_wet_at(river.level[i])) for i in flooding]
        print("  HAND vs NWS map agreement (IoU inside map coverage), per library stage:")
        stages = list(per_stage)
        print("    " + "  ".join(f"{s:.1f} ft: {per_stage[s]:.2f}"
                                 for s in sorted(set(stages[:: max(1, len(stages) // 6)] + [stages[-1]]))))
        if per_step:
            print(f"  ... at each {args.step_minutes}-min step with stage >= minor ({len(per_step)} steps): median "
                  f"{np.median(per_step):.2f}, min {min(per_step):.2f}, max {max(per_step):.2f}")
        report["hand_vs_nws_iou"] = {"per_library_stage": per_stage,
                                     "event_steps_median": float(np.median(per_step)) if per_step else None,
                                     "event_steps_min": float(min(per_step)) if per_step else None}
    else:
        print("  HAND vs NWS map: NWS publishes no flood-map library for this gauge; HAND cannot be validated here")

    n_seg = len(net.u)
    print(f"\nROADS ({road_counts['segments']} OSM segments as of {osm_date[:10]}; {road_counts['bridges']} bridges "
          f"exempt from flooding, {road_counts['tunnels']} tunnels NOT exempt: below grade, they flood first)")
    print(f"  segments whose river flooding is UNKNOWN (drain to mainstem outside the river driver's coverage): "
          f"{int(net.edge_stage_unknown.sum())} / {n_seg} = {net.edge_stage_unknown.mean():.1%}; bounded: passable "
          f"in the optimistic run, impassable at/above minor stage ({unknown_blocked.sum() * args.step_minutes / 60:.1f} h) "
          f"in the pessimistic run")
    print(f"  flooded (known) at worst step ({fmt(times[int(np.argmax(run.flooded_edges))])}): {run.flooded_edges.max()} / "
          f"{n_seg} = {run.flooded_edges.max() / n_seg:.1%}; ever flooded {run.edge_ever_flooded.sum()}")

    pops = bounds.populations
    status_n, status_pop = Counter(), Counter()
    for z in bounded.zones:
        status_n[z.status] += 1
        status_pop[z.status] += z.population
    print(f"\nZONES: {len(zones)} street blocks with residents (median {zone_geoms.area.median() / 1e3:.1f}k m2, "
          f"population {pops.sum():,})")
    notes = {"isolated": "confirmed (isolated even with unknown roads passable); countdown written",
             "possibly isolated": "only if unknown roads are flooded; earliest time + reason in coverage_gaps",
             "reachable": "reachable even with unknown roads impassable",
             "not connected at base flow": "not evaluated; reason in coverage_gaps",
             "no boundary roads": "not evaluated; reason in coverage_gaps"}
    for state, note in notes.items():
        print(f"  {state:27s} {status_n[state]:5d} zones  {status_pop[state]:8,d} people   {note}")
    iso_zones = [z for z in bounded.zones if z.status == "isolated"]
    possible = [z for z in bounded.zones if z.status == "possibly isolated"]
    stranded = [z for z in iso_zones if z.state_at_isolation == "stranded"]
    print(f"  confirmed isolated: stranded dry {len(stranded)} ({sum(z.population for z in stranded):,} people), "
          f"submerged {len(iso_zones) - len(stranded)}")

    signals = {
        "first road segment floods": next((t for t, n in zip(times, run.flooded_edges) if n), None),
        "first zone isolated": min((z.isolated_at for z in iso_zones), default=None),
        "first zone stranded dry": min((z.isolated_at for z in stranded), default=None),
        "earliest possible isolation": min((z.earliest_possible_isolation_at for z in iso_zones + possible), default=None),
    }
    print(f"\nLEAD TIME vs gauge minor-flood alarm ({fmt(alarm)}); + = signal before alarm, {args.step_minutes}-min "
          f"steps (river driver only)")
    for label, t in signals.items():
        lead = None if (t is None or alarm is None) else (alarm - t).total_seconds() / 60
        print(f"  {label:28s} {fmt(t):40s} {'none detected' if t is None else ('n/a' if lead is None else f'{lead:+.0f} min')}")

    print("\nCASES: opened and updated by the case matcher, not this pipeline "
          f"(.venv/bin/python scripts/run_case_matcher.py {site.site_id})")

    days = [claim_start + timedelta(days=d) for d in range((claim_end - claim_start).days + 1)]
    total = Counter()
    for c in claims.values():
        total.update(c)
    print(f"\nNFIP CLAIMS in the zones' {len(block_groups)} block groups (counties {', '.join(counties)}), "
          f"date of loss ({tz}):")
    print("  " + "  ".join(f"{d:%m-%d}:{total[d]}" for d in days))
    if total:
        peak_day = max(days, key=lambda d: total[d])
        day_start = datetime(peak_day.year, peak_day.month, peak_day.day, tzinfo=tz)
        print(f"  claims peak day {peak_day}")
        for label, t in (("gauge minor-flood alarm", alarm), *signals.items()):
            if t is not None:
                h = (day_start - t).total_seconds() / 3600
                print(f"  {label:28s} lead to claims-peak day: {h:+.1f} .. {h + 24:+.1f} h")
        report["claims_daily"] = {str(d): total[d] for d in days}

    print("\nSENTINEL-1 vs river-driver flood extent (inside the river driver's coverage)")
    s1_results = []
    rain_checks = []
    bbox = tuple(site.basin.bounds)
    for pre_ids, post_ids in sentinel1.find_pairs(bbox, start, end):
        try:
            pre, post = sentinel1.load_pass(pre_ids, bbox), sentinel1.load_pass(post_ids, bbox)
            water, pre_on_post = sentinel1.new_water(pre, post)
        except ValueError as exc:
            print(f"  {post_ids}: skipped ({exc})")
            continue
        i = int(np.argmin([abs((t - post.acquired_at).total_seconds()) for t in times]))

        def on_s1_grid(mask: np.ndarray) -> np.ndarray:
            out = np.zeros(water.shape, dtype="uint8")
            reproject(mask.astype("uint8"), out, src_transform=terrain.transform, src_crs=f"EPSG:{terrain.crs_epsg}",
                      dst_transform=post.transform, dst_crs=post.crs, resampling=Resampling.nearest)
            return out.astype(bool)

        valid = on_s1_grid(river.known) & np.isfinite(pre_on_post) & np.isfinite(post.vv_db)
        s1 = water & valid
        m = on_s1_grid(river_flood_mask(terrain, river, i)) & valid
        tp = int((m & s1).sum())
        line = {"post": post_ids, "pre": pre_ids, "acquired_at": str(post.acquired_at),
                "stage_ft": float(stage.stage_ft[i]), "stage_provenance": stage.provenance[i],
                "s1_new_water_km2": s1.sum() * 1e-4, "model_km2": m.sum() * 1e-4,
                "s1_inside_model": tp / s1.sum() if s1.sum() else None,
                "model_confirmed": tp / m.sum() if m.sum() else None,
                "csi": tp / (m | s1).sum() if (m | s1).sum() else None}
        pct = lambda x: "n/a" if x is None else f"{x:.1%}"
        print(f"  {post.orbit_state} {post.relative_orbit} {fmt(post.acquired_at)}  stage {line['stage_ft']:.1f} ft "
              f"[{line['stage_provenance']}]: S1 new water {line['s1_new_water_km2']:.2f} km2, model "
              f"{line['model_km2']:.2f} km2 | S1 water inside model {pct(line['s1_inside_model'])} | model "
              f"confirmed by S1 {pct(line['model_confirmed'])} | CSI {pct(line['csi'])}")

        # Rain driver validation on the same scene, across the whole basin.
        basin_valid = on_s1_grid(terrain.in_basin) & np.isfinite(pre_on_post) & np.isfinite(post.vv_db)
        s1_basin = water & basin_valid
        river_wet = river_flood_mask(terrain, river, i)
        line["rain"] = {}
        for frac, pond in rain_ponding.items():
            rm = on_s1_grid(rain_ponding_mask(terrain, pond.level_m[i], pond.catchments, river_wet)) & basin_valid
            hit = int((rm & s1_basin).sum())
            line["rain"][frac] = {"model_km2": rm.sum() * 1e-4, "confirmed": hit / rm.sum() if rm.sum() else None,
                                  "captures": hit / s1_basin.sum() if s1_basin.sum() else None}
        line["drains_reduced"] = bool(unknown_blocked[i])
        s1_results.append(line)
        rain_checks.append(line)
    if not s1_results:
        print("  no same-orbit Sentinel-1 pairs found for this basin and window")

    role = "FIT basin (parameters chosen here)" if site.site_id == RAIN_FIT_SITE else \
        f"HELD-OUT basin (parameters fit on USGS {RAIN_FIT_SITE}; nothing tuned here)"
    print(f"\nRAIN DRIVER VALIDATION ({role})")
    print(f"  parameters: depression >= {engine.DEPRESSION_MIN_M} m; drains keep {RESIDUAL_DRAIN_FRACTION:.0%} of "
          f"{capacity:.1f} mm/h at/above minor stage (bracket {', '.join(f'{f:.0%}' for f in RESIDUAL_DRAIN_BRACKET)}); "
          f"criterion: Sentinel-1 confirms rain ponding at least as often as the validated river driver")
    passes = []
    for line in rain_checks:
        base = line["model_confirmed"]
        r = line["rain"][RESIDUAL_DRAIN_FRACTION]
        bracket = "  ".join(f"{f:.0%}: {line['rain'][f]['model_km2']:.2f} km2 / {pct(line['rain'][f]['confirmed'])}"
                            for f in RESIDUAL_DRAIN_BRACKET)
        if base is None:
            verdict = "no baseline (river driver floods nothing at this scene)"
        elif r["confirmed"] is None:
            verdict = "cannot be checked: rain driver ponds nothing at this scene"
            passes.append(False)
        else:
            verdict = "clears" if r["confirmed"] >= base else "BELOW baseline"
            passes.append(r["confirmed"] >= base)
        print(f"  {line['acquired_at'][:16]} UTC (drains {'reduced' if line['drains_reduced'] else 'full'}): rain ponding "
              f"{r['model_km2']:.2f} km2, confirmed {pct(r['confirmed'])}, captures {pct(r['captures'])} of S1 water | "
              f"river baseline {pct(base)} -> {verdict}   [bracket {bracket}]")
    cleared = bool(passes) and all(passes)
    print(f"  VERDICT: {'clears' if cleared else 'does NOT clear (or cannot be checked against)'} the river-driver "
          f"baseline on this basin. "
          f"Rain driver stays gated off (RAIN_DRIVER_VALIDATED = {engine.RAIN_DRIVER_VALIDATED}); no rain-driven "
          f"isolation output.")
    report["rain_driver_validation"] = {"role": role, "cleared": cleared, "scenes": [
        {"acquired_at": x["acquired_at"], "river_confirmed": x["model_confirmed"], "rain": x["rain"]} for x in rain_checks]}

    report.update({
        "stage_provenance": dict(Counter(stage.provenance)),
        "flooded_edges_max": int(run.flooded_edges.max()),
        "unknown_river_segments": int(net.edge_stage_unknown.sum()),
        "zone_status": {state: {"zones": status_n[state], "people": status_pop[state]} for state in notes},
        "zones": [{"zone_id": z.zone_id, "block_group": z.block_group_geoid, "population": z.population,
                   "status": z.status, "isolated_at": z.isolated_at and str(z.isolated_at),
                   "earliest_possible_isolation_at": z.earliest_possible_isolation_at
                   and str(z.earliest_possible_isolation_at),
                   "state": z.state_at_isolation} for z in iso_zones + possible],
        "alarm_minor": alarm and str(alarm),
        "lead_minutes_vs_alarm": {k: None if (t is None or alarm is None) else (alarm - t).total_seconds() / 60
                                  for k, t in signals.items()},
        "sentinel1": s1_results,
    })
    out = os.path.join(cache, "backtest.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
