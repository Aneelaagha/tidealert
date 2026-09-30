"""Resolve everything the isolation pipeline needs from a USGS gauge ID alone.

- NHDPlus COMID, reach and location: NLDI crosswalk for nwissite/USGS-{site}.
- Study area: the gauge's upstream drainage basin from NLDI's basin endpoint.
- Gauge datum and time zone: USGS monitoring-location record (altitude of
  gauge datum and vertical datum, so stage can be converted to water-surface
  elevation; standard-time zone and whether daylight saving applies).
- Flood thresholds: NWS NWPS (AHPS) categories for the gauge. For any
  category NWS does not publish, an explicit, logged fallback is used:
  empirical percentiles of the gauge's USGS annual peak stages.
- NWS Flood Inundation Mapping library URL, when NWS publishes one (used only
  for validation).
"""
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import requests
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

log = logging.getLogger(__name__)

NLDI = "https://api.water.usgs.gov/nldi/linked-data"
NWPS = "https://api.water.noaa.gov/nwps/v1/gauges"
USGS_OGC = "https://api.waterdata.usgs.gov/ogcapi/v0/collections"

# Fallback rule when NWS publishes no threshold for a category: percentile of
# the gauge's annual peak gage heights. The 50th percentile is the ~2-year
# annual peak, a common proxy for bankfull / onset of flooding; the 80th and
# 90th approximate the 5- and 10-year peaks.
FALLBACK_PERCENTILES = {"minor": 50, "moderate": 80, "major": 90}
MIN_PEAKS_FOR_FALLBACK = 10
FEET_TO_METERS = 0.3048


@dataclass
class FloodThresholds:
    action_ft: Optional[float]
    minor_ft: float
    moderate_ft: float
    major_ft: float
    # Per category: "NWS <lid>" or "fallback: pNN of n annual peaks".
    provenance: dict[str, str]

    @property
    def any_fallback(self) -> bool:
        return any(p.startswith("fallback") for p in self.provenance.values())


@dataclass
class GaugeSite:
    site_id: str
    name: str
    point: Point
    comid: int
    basin: BaseGeometry
    gauge_datum_altitude_ft: Optional[float]
    gauge_vertical_datum: Optional[str]
    nws_lid: Optional[str]
    thresholds: FloodThresholds
    fim_mapserver_url: Optional[str]
    nws_time_zone: Optional[str]
    usgs_time_zone: Optional[str]  # standard-time abbreviation from the USGS site record, e.g. "CST"
    usgs_uses_dst: Optional[bool]

    @property
    def region(self) -> str:
        return f"USGS-{self.site_id} basin"

    def stage_to_wse_m(self, stage_ft: np.ndarray) -> Optional[np.ndarray]:
        """Water-surface elevation (m NAVD88) for a stage, when the gauge datum is NAVD88."""
        if self.gauge_vertical_datum != "NAVD88" or self.gauge_datum_altitude_ft is None:
            return None
        return (self.gauge_datum_altitude_ft + np.asarray(stage_ft)) * FEET_TO_METERS


def _get(url: str, **params) -> dict:
    resp = requests.get(url, params=params, timeout=180)
    resp.raise_for_status()
    return resp.json()


def _annual_peak_stages(site_id: str) -> list[float]:
    data = _get(
        f"{USGS_OGC}/peaks/items",
        f="json",
        monitoring_location_id=f"USGS-{site_id}",
        parameter_code="00065",
        limit=1000,
    )
    return [float(f["properties"]["value"]) for f in data["features"] if f["properties"]["value"] not in (None, "")]


def _thresholds(site_id: str, nwps: Optional[dict]) -> FloodThresholds:
    published: dict[str, Optional[float]] = {"action": None, "minor": None, "moderate": None, "major": None}
    lid = nwps["lid"] if nwps else None
    if nwps:
        for category in published:
            stage = (nwps.get("flood", {}).get("categories", {}).get(category) or {}).get("stage")
            # NWPS uses -9999 / 0 for "not defined".
            if stage is not None and stage > 0:
                published[category] = float(stage)

    provenance = {c: f"NWS {lid}" for c, v in published.items() if v is not None}
    missing = [c for c in FALLBACK_PERCENTILES if published[c] is None]
    if missing:
        peaks = _annual_peak_stages(site_id)
        if len(peaks) < MIN_PEAKS_FOR_FALLBACK:
            raise RuntimeError(
                f"USGS {site_id}: NWS publishes no {missing} flood stage and only {len(peaks)} annual peaks "
                f"exist (need {MIN_PEAKS_FOR_FALLBACK}) for the percentile fallback"
            )
        for category in missing:
            pct = FALLBACK_PERCENTILES[category]
            published[category] = float(np.percentile(peaks, pct))
            provenance[category] = f"fallback: p{pct} of {len(peaks)} annual peaks"
            log.warning(
                "USGS %s: NWS has no %s flood stage; FALLBACK to p%d of %d USGS annual peak stages = %.2f ft",
                site_id, category, pct, len(peaks), published[category],
            )
    return FloodThresholds(
        action_ft=published["action"],
        minor_ft=published["minor"],
        moderate_ft=published["moderate"],
        major_ft=published["major"],
        provenance=provenance,
    )


def resolve_gauge(site_id: str) -> GaugeSite:
    feature = _get(f"{NLDI}/nwissite/USGS-{site_id}", f="json")["features"][0]
    props = feature["properties"]
    basin_features = _get(f"{NLDI}/nwissite/USGS-{site_id}/basin", simplified="false", f="json")["features"]
    basin = shape(basin_features[0]["geometry"])

    location = _get(f"{USGS_OGC}/monitoring-locations/items/USGS-{site_id}", f="json")["properties"]

    resp = requests.get(f"{NWPS}/{site_id}", timeout=120)
    nwps = resp.json() if resp.ok else None
    if nwps is None:
        log.warning("USGS %s: no NWS NWPS gauge record (HTTP %s)", site_id, resp.status_code)

    inundation = (nwps or {}).get("inundation") or {}
    return GaugeSite(
        site_id=site_id,
        name=props["name"],
        point=shape(feature["geometry"]),
        comid=int(props["comid"]),
        basin=basin,
        gauge_datum_altitude_ft=location.get("altitude"),
        gauge_vertical_datum=location.get("vertical_datum"),
        nws_lid=nwps["lid"] if nwps else None,
        thresholds=_thresholds(site_id, nwps),
        fim_mapserver_url=inundation.get("url") if inundation.get("enabled") else None,
        nws_time_zone=(nwps or {}).get("timeZone"),
        usgs_time_zone=location.get("time_zone_abbreviation"),
        usgs_uses_dst={"Y": True, "N": False}.get(location.get("uses_daylight_savings")),
    )
