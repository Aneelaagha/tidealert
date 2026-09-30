"""Load one gauge's event data into the database: USGS stage/discharge, OSM roads, rainfall.

All inputs come from a resolved GaugeSite; nothing here is gauge-specific.

- USGS continuous gage height (00065) and discharge (00060) from the USGS
  Water Data OGC API -> signals, plus gauge_readings carrying the site's
  flood thresholds. Values qualified ESTIMATED are stored as inferred, not
  measured.
- OSM drivable roads inside the basin as of OSM_DATE (Overpass historical
  data), simplified without merging across OSM ways or bridge/tunnel
  boundaries, undirected -> road_segments. graph_edge_id is "<u>-<v>-<key>".
- Basin-mean hourly rainfall -> signals (inferred: AORC is an analysis).

Signal and segment ids are UUIDv5 of their natural keys, so re-runs upsert.
"""
import logging
import uuid
from datetime import datetime, timezone

import numpy as np
import osmnx as ox
import requests
from geoalchemy2.shape import from_shape
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import GaugeReading, RoadSegment, Signal
from app.models.data_source import SignalType
from app.services.data_sources import ensure_data_source
from app.services.gauge_site import GaugeSite
from app.services.rainfall import RainfallSeries
from app.services.stage import usgs_source_name

log = logging.getLogger(__name__)

USGS_CONTINUOUS ="https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items"
ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "tidealert:signals")
ROAD_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "tidealert:road_segments")


def signal_id(source: str, variable: str, observed_at: datetime) -> uuid.UUID:
    return uuid.uuid5(ID_NAMESPACE, f"{source}|{variable}|{observed_at.isoformat()}")


def _upsert_signals(db: Session, rows: list[dict]) -> int:
    if not rows:
        return 0
    stmt = insert(Signal).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={col: stmt.excluded[col] for col in ("signal_type", "value_num", "value_text", "geometry")},
    )
    return db.execute(stmt).rowcount


def _fetch_usgs(site_id: str, parameter_code: str, start: datetime, end: datetime) -> dict[datetime, tuple[float, list[str]]]:
    resp = requests.get(
        USGS_CONTINUOUS,
        params={
            "f": "json",
            "monitoring_location_id": f"USGS-{site_id}",
            "parameter_code": parameter_code,
            "datetime": f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}",
            "limit": 10000,
        },
        timeout=180,
    )
    resp.raise_for_status()
    series = {}
    for feature in resp.json()["features"]:
        props = feature["properties"]
        if props["value"] in (None, ""):
            continue
        series[datetime.fromisoformat(props["time"])] = (float(props["value"]), props.get("qualifier") or [])
    return series


def ingest_gauge(db: Session, site: GaugeSite, start: datetime, end: datetime) -> dict[str, int]:
    stage = _fetch_usgs(site.site_id, "00065", start, end)
    discharge = _fetch_usgs(site.site_id, "00060", start, end)
    if not stage:
        raise RuntimeError(f"USGS {site.site_id}: no gage height observations between {start} and {end}")

    source = ensure_data_source(
        db,
        name=usgs_source_name(site.site_id),
        category="river_gauge",
        cadence_seconds=900,
        stale_after_seconds=3600,
        type_default=SignalType.measured,
        url=f"https://waterdata.usgs.gov/monitoring-location/USGS-{site.site_id}/",
        license="Public domain (USGS)",
        notes=f"{site.name}. NWS {site.nws_lid or 'n/a'}. Gauge datum {site.gauge_datum_altitude_ft} ft "
              f"{site.gauge_vertical_datum}.",
    )
    geom = from_shape(site.point, srid=4326)

    def row(variable: str, t: datetime, value: float, qualifiers: list[str]) -> dict:
        return dict(
            id=signal_id(source.name, variable, t), source_id=source.id,
            signal_type=SignalType.inferred if "ESTIMATED" in qualifiers else SignalType.measured,
            variable=variable, value_num=value,
            value_text=f"USGS qualifier: {','.join(qualifiers)}" if qualifiers else None,
            geometry=geom, observed_at=t,
        )

    signals = [row("gage_height_ft", t, v, q) for t, (v, q) in sorted(stage.items())]
    signals += [row("discharge_cfs", t, v, q) for t, (v, q) in sorted(discharge.items())]
    readings = [
        dict(
            id=uuid.uuid5(ID_NAMESPACE, f"reading|{s['id']}"), signal_id=s["id"], usgs_site_id=site.site_id,
            stage_ft=s["value_num"],
            discharge_cfs=discharge[s["observed_at"]][0] if s["observed_at"] in discharge else None,
            datum=site.gauge_vertical_datum,
            flood_stage_ft=site.thresholds.minor_ft,
            moderate_stage_ft=site.thresholds.moderate_ft,
            major_stage_ft=site.thresholds.major_ft,
        )
        for s in signals if s["variable"] == "gage_height_ft"
    ]
    n_signals = _upsert_signals(db, signals)
    stmt = insert(GaugeReading).values(readings)
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={c: stmt.excluded[c] for c in ("stage_ft", "discharge_cfs", "datum", "flood_stage_ft",
                                            "moderate_stage_ft", "major_stage_ft")},
    )
    db.execute(stmt)
    db.commit()
    return {"stage": len(stage), "discharge": len(discharge), "signals": n_signals,
            "estimated": sum(s["signal_type"] == SignalType.inferred for s in signals)}


def _tag_is(value, excluded: set[str]) -> bool:
    """OSM tag present and not one of the excluded values (lists come from merged edges)."""
    values = value if isinstance(value, list) else [value]
    return any(isinstance(v, str) and v not in excluded for v in values)


def ingest_roads(db: Session, site: GaugeSite, osm_date: str) -> dict:
    """Fetch and store the basin's roads; returns counts and the graph_edge_ids loaded."""
    ox.settings.overpass_settings = f'[out:json][timeout:{{timeout}}]{{maxsize}}[date:"{osm_date}"]'
    ox.settings.useful_tags_way = list(dict.fromkeys(list(ox.settings.useful_tags_way) + ["bridge", "tunnel", "layer"]))
    # Always fetch from Overpass rather than osmnx's response cache, so each load is a real download.
    ox.settings.use_cache = False
    fetch_started = datetime.now(timezone.utc)
    log.info("USGS %s: Overpass fetch started %s with settings %s", site.site_id, fetch_started.isoformat(),
             ox.settings.overpass_settings.replace("{timeout}", str(ox.settings.requests_timeout)))
    graph = ox.graph_from_polygon(site.basin, network_type="drive", simplify=False, retain_all=True, truncate_by_edge=True)
    log.info("USGS %s: Overpass fetch finished %s: %d nodes, %d edges (unsimplified)", site.site_id,
             datetime.now(timezone.utc).isoformat(), graph.number_of_nodes(), graph.number_of_edges())
    graph = ox.simplify_graph(graph, edge_attrs_differ=["osmid", "bridge", "tunnel"])
    graph = ox.convert.to_undirected(graph)
    edges = ox.convert.graph_to_gdfs(graph, nodes=False, fill_edge_geometry=True)

    rows = []
    for (u, v, key), edge in edges.iterrows():
        osmid = edge["osmid"][0] if isinstance(edge["osmid"], list) else edge["osmid"]
        highway = edge["highway"]
        edge_id = f"{u}-{v}-{key}"
        rows.append(dict(
            id=uuid.uuid5(ROAD_NAMESPACE, edge_id),
            osm_way_id=int(osmid),
            geometry=from_shape(edge["geometry"], srid=4326),
            highway_class=";".join(highway) if isinstance(highway, list) else highway,
            # bridge=no / tunnel=no are explicit negatives; tunnel=culvert is a
            # pipe under an at-grade road, not a road tunnel.
            is_bridge=_tag_is(edge.get("bridge"), {"no"}),
            is_tunnel=_tag_is(edge.get("tunnel"), {"no", "culvert"}),
            graph_edge_id=edge_id,
        ))
    for i in range(0, len(rows), 5000):
        stmt = insert(RoadSegment).values(rows[i:i + 5000])
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={c: stmt.excluded[c] for c in ("osm_way_id", "geometry", "highway_class", "is_bridge", "is_tunnel")},
        )
        db.execute(stmt)
    db.commit()
    return {"segments": len(rows), "bridges": sum(r["is_bridge"] for r in rows),
            "tunnels": sum(r["is_tunnel"] for r in rows), "osm_date": osm_date,
            "fetched_at": fetch_started.isoformat(), "edge_ids": [r["graph_edge_id"] for r in rows]}


def ingest_rainfall(db: Session, site: GaugeSite, rain: RainfallSeries) -> int:
    source = ensure_data_source(
        db,
        name="AORC (NWM v2.1 retrospective forcing)",
        category="precipitation",
        cadence_seconds=3600,
        stale_after_seconds=3 * 3600,
        type_default=SignalType.inferred,
        url="https://registry.opendata.aws/nwm-archive/",
        license="Public domain (NOAA)",
        notes="NOAA Analysis of Record for Calibration (AORC), 1 km hourly gauge-corrected radar precipitation, "
              "read from s3://noaa-nwm-retrospective-2-1-zarr-pds/precip.zarr; value is the mean rate over the "
              "hour ending at the observation time. Used as the rainfall driver in place of NASA GPM IMERG, "
              "which requires NASA Earthdata credentials.",
    )
    geom = from_shape(site.basin.centroid, srid=4326)
    variable = f"basin_mean_precip_mm_hr:USGS-{site.site_id}"
    rows = [
        dict(id=signal_id(source.name, variable, t), source_id=source.id, signal_type=SignalType.inferred,
             variable=variable, value_num=float(v), value_text=None, geometry=geom, observed_at=t)
        for t, v in zip(rain.times, np.asarray(rain.basin_mean_mm_hr))
    ]
    n = _upsert_signals(db, rows)
    db.commit()
    return n
