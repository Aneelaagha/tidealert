import geopandas as gpd
import pandas as pd
import requests

TIGERWEB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
# Census geography layers per decennial vintage.
BLOCK_GROUP_LAYERS = {
    2010: f"{TIGERWEB}/tigerWMS_Census2010/MapServer/16",
    2020: f"{TIGERWEB}/tigerWMS_Census2020/MapServer/8",
}
BLOCK_LAYER_2020 = f"{TIGERWEB}/tigerWMS_Census2020/MapServer/10"
PAGE_SIZE = 1000


def _query_bbox(layer_url: str, bbox: tuple[float, float, float, float], out_fields: str) -> gpd.GeoDataFrame:
    """All features of a TIGERweb layer intersecting a (west, south, east, north) bbox, in EPSG:4326."""
    west, south, east, north = bbox
    pages = []
    offset = 0
    while True:
        resp = requests.get(
            f"{layer_url}/query",
            params={
                "geometry": f"{west},{south},{east},{north}",
                "geometryType": "esriGeometryEnvelope",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": out_fields,
                "outSR": 4326,
                "orderByFields": "GEOID",
                "resultOffset": offset,
                "resultRecordCount": PAGE_SIZE,
                "f": "geojson",
            },
            timeout=300,
        )
        resp.raise_for_status()
        features = resp.json()["features"]
        if features:
            pages.append(gpd.GeoDataFrame.from_features(features, crs=4326))
        if len(features) < PAGE_SIZE:
            break
        offset += len(features)
    if not pages:
        return gpd.GeoDataFrame({"GEOID": []}, geometry=[], crs=4326)
    return gpd.GeoDataFrame(pd.concat(pages, ignore_index=True), crs=4326)


def fetch_block_groups(vintage: int, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Census block groups of one vintage intersecting a (west, south, east, north) bbox, in EPSG:4326."""
    fields = "GEOID,POP100,HU100" if vintage == 2020 else "GEOID"
    return _query_bbox(BLOCK_GROUP_LAYERS[vintage], bbox, fields)


def fetch_blocks_2020(bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """2020 census blocks (with population) intersecting a (west, south, east, north) bbox, in EPSG:4326."""
    return _query_bbox(BLOCK_LAYER_2020, bbox, "GEOID,POP100")
