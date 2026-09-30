import geopandas as gpd
import requests

TIGERWEB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
# Census block group layers per decennial vintage.
BLOCK_GROUP_LAYERS = {
    2010: f"{TIGERWEB}/tigerWMS_Census2010/MapServer/16",
    2020: f"{TIGERWEB}/tigerWMS_Census2020/MapServer/8",
}


def fetch_block_groups(vintage: int, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Census block groups of one vintage intersecting a (west, south, east, north) bbox, in EPSG:4326."""
    west, south, east, north = bbox
    resp = requests.get(
        f"{BLOCK_GROUP_LAYERS[vintage]}/query",
        params={
            "geometry": f"{west},{south},{east},{north}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "GEOID,POP100,HU100" if vintage == 2020 else "GEOID",
            "outSR": 4326,
            "f": "geojson",
        },
        timeout=180,
    )
    resp.raise_for_status()
    return gpd.GeoDataFrame.from_features(resp.json()["features"], crs=4326)
