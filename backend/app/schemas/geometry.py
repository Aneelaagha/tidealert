from typing import Any

from geoalchemy2.elements import WKBElement


def wkb_to_geojson(value: Any) -> Any:
    """Convert a PostGIS geometry loaded by GeoAlchemy2 into a GeoJSON dict."""
    if isinstance(value, WKBElement):
        from geoalchemy2.shape import to_shape
        from shapely.geometry import mapping

        return mapping(to_shape(value))
    return value
