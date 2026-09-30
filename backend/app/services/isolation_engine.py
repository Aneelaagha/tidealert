"""Isolation engine: when does each zone lose every road route to high ground?

Pipeline, per hourly timestep:

    gauge stage -> NWS FIM inundation extent -> flooded road segments removed
    (bridges/tunnels exempt) -> connected components -> per-zone reachability

Inputs are all real data already loaded in the database or data directory:

- road_segments (OSM, as of 2017-08-24), rebuilt into an undirected graph via
  graph_edge_id "<u>-<v>-<key>".
- The NWS FIM library for HGTT2 (fim_extents.gpkg): one inundation extent per
  1 ft of stage. A stage maps to the smallest library stage >= it, which is
  the convention NWS uses for its own flood-category maps (e.g. minor 32 ft
  is drawn with the 32.7 ft grid). Below the lowest library stage nothing is
  flooded; above the highest, the highest extent is used.
- A USGS 3DEP DEM for picking high-ground nodes.
- zones (census block groups).

Definitions:

- A segment is flooded at stage S when at least MIN_WET_LENGTH_M of it lies
  inside the extent for S. Bridges and tunnels are never flooded (spec §2).
- High-ground nodes: road nodes with ground elevation at least
  HIGH_GROUND_FREEBOARD_M above the event's peak water-surface elevation at
  the gauge and outside the largest FIM extent.
- The "main network" at a timestep is the connected component of the
  surviving graph containing the most high-ground nodes. A zone is isolated
  when none of its road nodes is in the main network. This also catches a
  zone cut off on a high-ground island.
- A cut-off road node is "submerged" when every road touching it is flooded,
  and "stranded" when it is still dry (some road touching it is passable) but
  none of its routes reach the main network. Stranded nodes are the finer
  isolation signal; a zone is only isolated when all of its nodes are cut off.

Flooding is only known inside the FIM library's reach. Everything outside it
is treated as passable.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import geopandas as gpd
import networkx as nx
import numpy as np
import rasterio
from geoalchemy2.shape import to_shape
from shapely.geometry import Point
from shapely.prepared import prep
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RoadSegment, Zone
from app.services.stage import HourlyStage

METRIC_CRS = 32615  # UTM 15N
MIN_WET_LENGTH_M = 6.0  # two FIM pixels; ignores rendering-edge slivers
HIGH_GROUND_FREEBOARD_M = 1.0
NEVER = np.inf


@dataclass
class FimLibrary:
    stages_ft: np.ndarray
    extents: list  # shapely geometries in METRIC_CRS, nested, ascending stage

    @classmethod
    def load(cls, path: str) -> "FimLibrary":
        gdf = gpd.read_file(path, layer="inundation_extents").sort_values("stage_ft").to_crs(METRIC_CRS)
        return cls(stages_ft=gdf["stage_ft"].to_numpy(), extents=list(gdf.geometry))

    def layer_for_stage(self, stage_ft: float) -> int:
        """Index of the extent in effect at this stage, or -1 for no inundation."""
        if stage_ft < self.stages_ft[0]:
            return -1
        return int(min(np.searchsorted(self.stages_ft, stage_ft, side="left"), len(self.stages_ft) - 1))


@dataclass
class RoadGraph:
    graph: nx.MultiGraph
    node_xy: dict[int, tuple[float, float]]  # METRIC_CRS
    # Per edge (u, v, key): index of the lowest FIM layer that floods it, or NEVER.
    edge_flood_layer: dict[tuple[int, int, int], float]
    n_bridge_or_tunnel_exempt: int


@dataclass
class ZoneResult:
    zone_id: str
    census_geoid: str
    n_nodes: int
    first_isolated_at: Optional[datetime]
    reconnected_at: Optional[datetime]
    # First hour any of the zone's road nodes is cut off from the main network.
    first_partial_cut_at: Optional[datetime]
    min_reachable_fraction: float
    min_reachable_at: datetime
    reachable_fraction: list[float] = field(repr=False)

    def countdown_minutes(self, now: datetime) -> Optional[int]:
        """Minutes from `now` until isolation (0 if already isolated), None if never isolated."""
        if self.first_isolated_at is None:
            return None
        return max(0, int((self.first_isolated_at - now).total_seconds() // 60))


@dataclass
class IsolationRun:
    stage: HourlyStage
    layer_index: list[int]
    flooded_edge_count: list[int]
    # Cut-off road nodes inside zones, per timestep.
    stranded_node_count: list[int]
    submerged_node_count: list[int]
    zones: list[ZoneResult]
    n_high_ground_nodes: int


def _resolve_node_coordinates(edges: list[tuple[int, int, list]]) -> dict[int, tuple[float, float]]:
    """Recover node coordinates from edge geometries whose orientation is unknown.

    A node's true coordinate is shared by every incident edge's endpoints, so
    for nodes with degree >= 2 it is the most common candidate endpoint.
    Degree-1 nodes take whichever endpoint is not their neighbour's coordinate.
    """
    candidates: dict[int, Counter] = {}
    for u, v, coords in edges:
        ends = (tuple(coords[0]), tuple(coords[-1]))
        for n in (u, v):
            candidates.setdefault(n, Counter()).update(ends)

    resolved = {n: c.most_common(1)[0][0] for n, c in candidates.items() if c.most_common(1)[0][1] >= 2}
    for u, v, coords in edges:
        ends = (tuple(coords[0]), tuple(coords[-1]))
        for n, other in ((u, v), (v, u)):
            if n in resolved:
                continue
            if other in resolved:
                resolved[n] = ends[1] if ends[0] == resolved[other] else ends[0]
    return resolved


def load_road_graph(db: Session, fim: FimLibrary) -> RoadGraph:
    segments = gpd.GeoDataFrame(
        [
            {
                "edge_id": s.graph_edge_id,
                "is_exempt": s.is_bridge or s.is_tunnel,
                "geometry": to_shape(s.geometry),
            }
            for s in db.scalars(select(RoadSegment))
        ],
        crs=4326,
    ).to_crs(METRIC_CRS)

    graph = nx.MultiGraph()
    edge_coords = []
    keys = []
    for row in segments.itertuples():
        u, v, k = (int(x) for x in row.edge_id.split("-"))
        graph.add_edge(u, v, key=k)
        edge_coords.append((u, v, list(row.geometry.coords)))
        keys.append((u, v, k))
    node_xy = _resolve_node_coordinates(edge_coords)

    # Lowest FIM layer that floods each edge. Extents are nested, so scan
    # downward from the largest and stop at the first layer that is too dry.
    largest = prep(fim.extents[-1])
    edge_flood_layer = {}
    n_exempt = 0
    for key, row in zip(keys, segments.itertuples()):
        edge_flood_layer[key] = NEVER
        if not largest.intersects(row.geometry):
            continue
        if row.is_exempt:
            n_exempt += 1
            continue
        for layer in range(len(fim.extents) - 1, -1, -1):
            if row.geometry.intersection(fim.extents[layer]).length >= MIN_WET_LENGTH_M:
                edge_flood_layer[key] = layer
            else:
                break
    return RoadGraph(graph=graph, node_xy=node_xy, edge_flood_layer=edge_flood_layer, n_bridge_or_tunnel_exempt=n_exempt)


def high_ground_nodes(road: RoadGraph, fim: FimLibrary, dem_path: str, peak_wse_m: float) -> set[int]:
    nodes = list(road.node_xy)
    with rasterio.open(dem_path) as dem:
        if dem.crs.to_epsg() != METRIC_CRS:
            raise ValueError(f"DEM must be in EPSG:{METRIC_CRS}, got {dem.crs}")
        elevations = np.array([v[0] for v in dem.sample([road.node_xy[n] for n in nodes], masked=True)])
    largest = prep(fim.extents[-1])
    threshold = peak_wse_m + HIGH_GROUND_FREEBOARD_M
    return {
        n
        for n, elev in zip(nodes, elevations)
        if elev is not np.ma.masked and elev >= threshold and not largest.contains(Point(road.node_xy[n]))
    }


def zone_nodes(db: Session, road: RoadGraph) -> dict[Zone, list[int]]:
    zones = list(db.scalars(select(Zone).where(Zone.census_geoid.is_not(None)).order_by(Zone.census_geoid)))
    polygons = gpd.GeoSeries([to_shape(z.boundary) for z in zones], crs=4326).to_crs(METRIC_CRS)
    node_ids = list(road.node_xy)
    points = gpd.GeoSeries([Point(road.node_xy[n]) for n in node_ids], crs=METRIC_CRS)
    result = {}
    for zone, polygon in zip(zones, polygons):
        inside = points.within(polygon).to_numpy()
        result[zone] = [n for n, hit in zip(node_ids, inside) if hit]
    return result


def run_isolation(
    road: RoadGraph,
    fim: FimLibrary,
    stage: HourlyStage,
    zones: dict[Zone, list[int]],
    high_ground: set[int],
) -> IsolationRun:
    layer_index = [fim.layer_for_stage(s) for s in stage.stage_ft]
    reachable: dict[Zone, list[float]] = {z: [] for z in zones}
    flooded_counts, stranded_counts, submerged_counts = [], [], []
    cache: dict[int, tuple[int, set[int], int, int]] = {}
    zone_node_set = {n for nodes in zones.values() for n in nodes}

    for layer in layer_index:
        if layer not in cache:
            surviving = road.graph.copy()
            flooded = [e for e, first in road.edge_flood_layer.items() if first <= layer]
            surviving.remove_edges_from(flooded)
            components = list(nx.connected_components(surviving))
            main = max(components, key=lambda c: len(c & high_ground))
            cut = zone_node_set - main
            submerged = sum(1 for n in cut if surviving.degree(n) == 0)
            cache[layer] = (len(flooded), main, len(cut) - submerged, submerged)
        n_flooded, main, n_stranded, n_submerged = cache[layer]
        flooded_counts.append(n_flooded)
        stranded_counts.append(n_stranded)
        submerged_counts.append(n_submerged)
        for zone, nodes in zones.items():
            reachable[zone].append(sum(n in main for n in nodes) / len(nodes) if nodes else 0.0)

    results = []
    for zone, fractions in reachable.items():
        first = next((i for i, f in enumerate(fractions) if f == 0.0), None)
        partial = next((i for i, f in enumerate(fractions) if f < 1.0), None)
        worst = int(np.argmin(fractions))
        back = None
        if first is not None:
            back = next((i for i in range(first, len(fractions)) if fractions[i] > 0.0), None)
        results.append(
            ZoneResult(
                zone_id=str(zone.id),
                census_geoid=zone.census_geoid,
                n_nodes=len(zones[zone]),
                first_isolated_at=stage.times[first] if first is not None else None,
                reconnected_at=stage.times[back] if back is not None else None,
                first_partial_cut_at=stage.times[partial] if partial is not None else None,
                min_reachable_fraction=fractions[worst],
                min_reachable_at=stage.times[worst],
                reachable_fraction=fractions,
            )
        )
    return IsolationRun(
        stage=stage,
        layer_index=layer_index,
        flooded_edge_count=flooded_counts,
        stranded_node_count=stranded_counts,
        submerged_node_count=submerged_counts,
        zones=results,
        n_high_ground_nodes=len(high_ground),
    )


def update_zone_countdowns(db: Session, run: IsolationRun, now: datetime) -> None:
    """Write each zone's countdown to isolation, as of `now`, to zones.isolation_minutes."""
    by_id = {r.zone_id: r for r in run.zones}
    for zone in db.scalars(select(Zone).where(Zone.census_geoid.is_not(None))):
        result = by_id.get(str(zone.id))
        if result is not None:
            zone.isolation_minutes = result.countdown_minutes(now)
    db.commit()
