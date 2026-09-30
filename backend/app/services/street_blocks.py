"""Generate last-mile zones for a gauge's basin: OSM street blocks with residents.

A street block is a face of the drivable road network: the area enclosed by
the road segments around it (polygonized from road_segments inside the
basin). Each block gets the 2020 census population of the census blocks it
overlaps, by area share, and the 2020 block group it mostly falls in (used to
join NFIP claims, which are located by block group). Blocks with no
residents are dropped. Faces smaller than MIN_BLOCK_AREA_M2 are slivers from
overlapping road geometry, not blocks.

Zones are replaced wholesale for the basin's region on every run.
"""
from datetime import datetime, timezone

import geopandas as gpd
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import MultiPolygon
from shapely.ops import polygonize, unary_union
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import RoadSegment, Zone
from app.services.census import fetch_blocks_2020
from app.services.gauge_site import GaugeSite

MIN_BLOCK_AREA_M2 = 200.0
MIN_POPULATION = 0.5  # area-weighted; rounds to at least one resident


def basin_segments(db: Session, site: GaugeSite, crs_epsg: int, edge_ids: list[str]) -> gpd.GeoDataFrame:
    """The basin's road segments from one roads load (edge_ids), so other loads' overlapping segments are excluded."""
    rows = db.execute(
        select(RoadSegment.id, RoadSegment.graph_edge_id, RoadSegment.is_bridge,
               RoadSegment.highway_class, RoadSegment.geometry)
        .where(func.ST_Intersects(RoadSegment.geometry, from_shape(site.basin, srid=4326)))
        .where(RoadSegment.graph_edge_id.in_(edge_ids))
    ).all()
    return gpd.GeoDataFrame(
        {
            "segment_id": [r.id for r in rows],
            "edge_id": [r.graph_edge_id for r in rows],
            # Only bridges are exempt from flooding: they sit above the flood surface. Tunnels and
            # underpasses are below grade and flood first (a deliberate deviation from spec §2).
            "is_exempt": [r.is_bridge for r in rows],
            "highway_class": [r.highway_class for r in rows],
        },
        geometry=[to_shape(r.geometry) for r in rows],
        crs=4326,
    ).to_crs(crs_epsg)


def generate_zones(db: Session, site: GaugeSite, crs_epsg: int, edge_ids: list[str]) -> gpd.GeoDataFrame:
    segments = basin_segments(db, site, crs_epsg, edge_ids)
    basin = gpd.GeoSeries([site.basin], crs=4326).to_crs(crs_epsg).iloc[0]
    faces = gpd.GeoSeries(list(polygonize(unary_union(list(segments.geometry)))), crs=crs_epsg)
    faces = faces.intersection(basin)
    faces = faces[faces.area >= MIN_BLOCK_AREA_M2]
    blocks = gpd.GeoDataFrame({"face": range(len(faces))}, geometry=faces.values, crs=crs_epsg)

    census = fetch_blocks_2020(tuple(site.basin.bounds)).to_crs(crs_epsg)
    census["census_area"] = census.area
    pieces = gpd.overlay(blocks, census[["GEOID", "POP100", "census_area", "geometry"]], how="intersection",
                         keep_geom_type=True)
    pieces["pop_share"] = pieces["POP100"] * pieces.area / pieces["census_area"]
    pieces["piece_area"] = pieces.area
    population = pieces.groupby("face")["pop_share"].sum()
    main_piece = pieces.sort_values("piece_area").groupby("face").tail(1).set_index("face")

    blocks["population"] = blocks["face"].map(population).fillna(0.0)
    blocks["block_group_geoid"] = blocks["face"].map(main_piece["GEOID"].str[:12])
    blocks = blocks[blocks["population"] >= MIN_POPULATION].reset_index(drop=True)

    now = datetime.now(timezone.utc)
    db.execute(delete(Zone).where(Zone.region == site.region))
    geoms_4326 = blocks.to_crs(4326).geometry
    for i, (row, geom) in enumerate(zip(blocks.itertuples(), geoms_4326)):
        if isinstance(geom, MultiPolygon):
            # zones.boundary is a POLYGON; a basin-clipped block can split. Keep its main part.
            geom = max(geom.geoms, key=lambda g: g.area)
        db.add(Zone(
            name=f"USGS-{site.site_id} street block {i + 1}",
            region=site.region,
            boundary=from_shape(geom, srid=4326),
            block_group_geoid=row.block_group_geoid,
            population_count=int(round(row.population)),
            last_updated_at=now,
        ))
    db.commit()
    return blocks
