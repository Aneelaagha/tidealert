"""Load Hurricane Harvey hydrology for White Oak Bayou into signals / gauge_readings.

Two sources, kept separate because they differ in trust level:

1. USGS 08074500 (Whiteoak Bayou at Houston) observed 15-minute gage height
   and discharge, approved record, from the USGS Water Data OGC API.
   -> signals (measured) + gauge_readings (one per gage-height observation).

2. NOAA National Water Model v2.1 retrospective CHRTOUT hourly streamflow for
   NHDPlus COMID 1440291, the reach the gauge sits on (resolved via NLDI).
   -> signals (inferred) only: NWM produces discharge, not stage, and
   gauge_readings.stage_ft is required. Read from the Zarr conversion of the
   retrospective (noaa-nwm-retrospective-2-1-zarr-pds); spot-checked
   identical to the NetCDF CHRTOUT files in noaa-nwm-retrospective-2-1-pds.

Flood categories are the NWS AHPS values for HGTT2 (same gauge): minor
(flood stage) 32 ft, moderate 33.5 ft, major 36 ft. Gauge datum is 0 ft
NAVD88 per both USGS and NWS, so stage == water-surface elevation (ft NAVD88).

USGS values qualified ESTIMATED (the gauge stopped recording stage from
2017-08-27 10:30 UTC to 2017-08-31 21:30 UTC; USGS estimated discharge every
2 h through that gap) are stored as inferred, not measured, with the qualifier
in value_text.

Signal ids are UUIDv5 of (source, variable, time), so re-runs are idempotent.

Usage (from the repo root):
    .venv/bin/python scripts/pull_gauge_nwm.py
"""
import os
import sys
import uuid
from datetime import datetime

import requests
import s3fs
import xarray as xr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from geoalchemy2.shape import from_shape  # noqa: E402
from shapely.geometry import Point  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import GaugeReading, Signal  # noqa: E402
from app.models.data_source import SignalType  # noqa: E402
from app.services.data_sources import ensure_data_source  # noqa: E402

USGS_SITE = "08074500"
NWS_LID = "HGTT2"
COMID = 1440291
# Gauge location from NLDI / USGS site record.
GAUGE_POINT = Point(-95.3971612, 29.77522777)

START = "2017-08-25T00:00:00Z"
END = "2017-09-03T05:00:00Z"  # through the end of 2017-09-02 US Central time

# NWS AHPS flood categories for HGTT2 (ft, gauge datum = 0 ft NAVD88).
FLOOD_STAGE_FT = 32.0
MODERATE_STAGE_FT = 33.5
MAJOR_STAGE_FT = 36.0

USGS_API = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items"
NWM_ZARR = "noaa-nwm-retrospective-2-1-zarr-pds/chrtout.zarr"
M3S_TO_CFS = 35.3146667

ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "tidealert:signals")


def signal_id(source: str, variable: str, observed_at: datetime) -> uuid.UUID:
    return uuid.uuid5(ID_NAMESPACE, f"{source}|{variable}|{observed_at.isoformat()}")


def fetch_usgs(parameter_code: str) -> dict[datetime, tuple[float, list[str]]]:
    """Return {time: (value, qualifiers)} for one USGS parameter."""
    resp = requests.get(
        USGS_API,
        params={
            "f": "json",
            "monitoring_location_id": f"USGS-{USGS_SITE}",
            "parameter_code": parameter_code,
            "datetime": f"{START}/{END}",
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


def fetch_nwm() -> dict[datetime, float]:
    store = s3fs.S3Map(NWM_ZARR, s3=s3fs.S3FileSystem(anon=True))
    ds = xr.open_zarr(store, consolidated=True)
    q = ds.streamflow.sel(feature_id=COMID, time=slice(START[:-1], END[:-1])).load()
    return {
        datetime.fromisoformat(str(t)[:19] + "+00:00"): float(v) * M3S_TO_CFS
        for t, v in zip(q.time.values, q.values)
    }


def main() -> None:
    gauge_geom = from_shape(GAUGE_POINT, srid=4326)

    stage = fetch_usgs("00065")
    discharge = fetch_usgs("00060")
    nwm = fetch_nwm()
    print(f"USGS gage height: {len(stage)} obs, discharge: {len(discharge)} obs; NWM: {len(nwm)} hours")

    with SessionLocal() as db:
        usgs_source = ensure_data_source(
            db,
            name=f"USGS {USGS_SITE} continuous",
            category="river_gauge",
            cadence_seconds=900,
            stale_after_seconds=3600,
            type_default=SignalType.measured,
            url=f"https://waterdata.usgs.gov/monitoring-location/USGS-{USGS_SITE}/",
            license="Public domain (USGS)",
            notes=f"Whiteoak Bayou at Houston, TX (NWS {NWS_LID}). Gauge datum 0 ft NAVD88.",
        )
        nwm_source = ensure_data_source(
            db,
            name="NWM v2.1 retrospective CHRTOUT",
            category="hydrologic_model",
            cadence_seconds=3600,
            stale_after_seconds=3 * 3600,
            type_default=SignalType.inferred,
            url="https://registry.opendata.aws/nwm-archive/",
            license="Public domain (NOAA)",
            notes="Uncalibrated reanalysis; overpredicts Harvey peak at COMID 1440291 by ~50%.",
        )

        def usgs_signal(variable: str, t: datetime, value: float, qualifiers: list[str]) -> dict:
            estimated = "ESTIMATED" in qualifiers
            return dict(
                id=signal_id(usgs_source.name, variable, t), source_id=usgs_source.id,
                signal_type=SignalType.inferred if estimated else SignalType.measured,
                variable=variable, value_num=value,
                value_text=f"USGS qualifier: {','.join(qualifiers)}" if qualifiers else None,
                geometry=gauge_geom, observed_at=t,
            )

        signal_rows, reading_rows = [], []
        for t, (value, qualifiers) in sorted(stage.items()):
            row = usgs_signal("gage_height_ft", t, value, qualifiers)
            signal_rows.append(row)
            reading_rows.append(
                dict(id=uuid.uuid5(ID_NAMESPACE, f"reading|{row['id']}"), signal_id=row["id"],
                     usgs_site_id=USGS_SITE, stage_ft=value,
                     discharge_cfs=discharge[t][0] if t in discharge else None, datum="NAVD88",
                     flood_stage_ft=FLOOD_STAGE_FT, moderate_stage_ft=MODERATE_STAGE_FT,
                     major_stage_ft=MAJOR_STAGE_FT)
            )
        for t, (value, qualifiers) in sorted(discharge.items()):
            signal_rows.append(usgs_signal("discharge_cfs", t, value, qualifiers))
        for t, value in sorted(nwm.items()):
            signal_rows.append(
                dict(id=signal_id(nwm_source.name, "streamflow_cfs", t), source_id=nwm_source.id,
                     signal_type=SignalType.inferred, variable="streamflow_cfs", value_num=value,
                     value_text=f"comid={COMID}", geometry=gauge_geom, observed_at=t)
            )

        stmt = insert(Signal).values(signal_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={col: stmt.excluded[col] for col in ("signal_type", "value_num", "value_text")},
        )
        n_signals = db.execute(stmt).rowcount
        n_readings = db.execute(insert(GaugeReading).values(reading_rows).on_conflict_do_nothing()).rowcount
        db.commit()
        n_estimated = sum(
            r["signal_type"] == SignalType.inferred for r in signal_rows if r["source_id"] == usgs_source.id
        )

    peak_t = max(stage, key=lambda t: stage[t][0])
    nwm_peak_t = max(nwm, key=nwm.get)
    print(f"Upserted {n_signals} signals ({n_estimated} USGS values qualified ESTIMATED), "
          f"inserted {n_readings} new gauge readings")
    print(f"Observed peak: {stage[peak_t][0]:.2f} ft / {discharge[peak_t][0]:,.0f} cfs at {peak_t}")
    print(f"NWM peak:      {nwm[nwm_peak_t]:,.0f} cfs at {nwm_peak_t}")
    first_flood = min((t for t, (v, _) in stage.items() if v >= FLOOD_STAGE_FT), default=None)
    print(f"First obs at/above flood stage ({FLOOD_STAGE_FT} ft): {first_flood}")


if __name__ == "__main__":
    main()
