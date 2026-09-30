"""Isolation engine: when does each zone lose every road route out?

Per timestep:

    gauge stage -> river level -> river-driver flooding               (driver "stage")
    rainfall    -> per-catchment ponding level -> HAND(network) ponding (driver "rain", NOT YET VALIDATED)
    flooded road segments removed (bridges exempt; tunnels are not, see below)
    -> connected components -> per-zone reachability

The river driver is generic: each road sample has a threshold and each
timestep a river level, in the same units, and a sample is wet when
threshold <= level. The pipeline supplies one of two sources:

- NWS flood map (primary, where NWS publishes a library): threshold = lowest
  library stage whose mapped extent contains the sample (ft); level = the
  library stage in effect (next layer up from the gauge stage, NWS's own
  convention; nothing floods below the lowest layer).
- HAND (only where no library exists; lower confidence): threshold =
  HAND(mainstem) (m); level = depth over the gauge's channel (m).

Definitions:

- Each road segment is sampled every SAMPLE_SPACING_M. A segment is flooded
  when at least MIN_WET_SAMPLES samples are wet (~10 m of road), under either
  driver.
- The main network is the largest connected component of the surviving
  road graph.
- A zone (street block) is reachable while at least one road on its boundary
  is dry and part of the main network. A zone is isolated when none is.
  An isolated zone is "stranded" if some boundary road is still dry (dry
  but cut off) and "submerged" if every boundary road is flooded.
- The river driver only applies where its source actually covers the river:
  inside the NWS map's mapped extent, or (HAND) draining to the gauge's own
  reach. Roads draining to the mainstem outside that coverage have unknown
  river flooding. Reachability is bounded (run_bounded): an optimistic run
  treats unknown roads as passable, a pessimistic run treats them as flooded
  while the gauge is at/above minor flood stage. Zones are "isolated"
  (confirmed: isolated even in the optimistic run), "possibly isolated"
  (pessimistic run only, with an earliest-possible isolation time) or
  "reachable".
- Rain ponding is capped at the receiving water level: outside closed
  depressions a sample ponds only where the river driver already has water;
  where that level is unmeasured, only closed depressions pond, and roads
  that would pond beyond them are "rain unknown", handled like stage-unknown.
- Zones not connected to the main network even with every road dry are
  "not connected at base flow" and are not evaluated.
- Only bridges are exempt from flooding: they are elevated above the DEM
  surface the flood sources describe. Tunnels and underpasses are below
  grade and flood first, so they are not exempt. (Spec §2 exempted both;
  this is a deliberate, documented deviation.)
- The rain driver is gated off (RAIN_DRIVER_VALIDATED) and produces no
  isolation output until it matches the river driver's Sentinel-1
  confirmation on held-out basins. See docs/algorithms/isolation-engine.md.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import geopandas as gpd
import numpy as np
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from shapely.strtree import STRtree
from sqlalchemy.orm import Session

from app.models import Zone
from app.services.terrain import Terrain

SAMPLE_SPACING_M = 5.0
MIN_WET_SAMPLES = 2
BOUNDARY_TOLERANCE_M = 1.0
# A cell counts as a closed depression (for rain ponding) when filling raises it at least this much.
# 0.5 m, fit on Greens Bayou against Sentinel-1: shallower "depressions" are mostly street sags at
# storm inlets (61-64% of rain-flooded road samples were 0.15-0.3 m deep) and roughly halved the
# share of modeled ponding that Sentinel-1 confirmed.
DEPRESSION_MIN_M = 0.5
# The rain (ponding) driver must not produce isolation output until it matches the validated river
# driver's Sentinel-1 confirmation on held-out basins (see the pipeline's rain validation section and
# docs/algorithms/isolation-engine.md). Only change this by hand, after reviewing that evidence.
RAIN_DRIVER_VALIDATED = False


class UnvalidatedDriverError(RuntimeError):
    """A driver that has not been validated was asked to produce isolation output."""


@dataclass
class RoadNetwork:
    edge_ids: list[str]
    u: np.ndarray  # node index per edge
    v: np.ndarray
    n_nodes: int
    exempt: np.ndarray  # bool per edge
    geometry: gpd.GeoSeries  # metric CRS
    # One row per sample point along an edge.
    sample_edge: np.ndarray
    sample_river_threshold: np.ndarray  # river level at which the sample floods (inf: never within range)
    sample_hand_network: np.ndarray
    sample_catchment: np.ndarray  # index into the ponding catchments, -1 if none
    sample_stage_known: np.ndarray  # bool: inside the river driver's coverage
    sample_depression: np.ndarray  # bool: inside a closed depression (see DEPRESSION_MIN_M)
    edge_stage_unknown: np.ndarray  # bool per edge: some sample drains to the mainstem outside it
    edge_rain_unknown: np.ndarray  # bool per edge: set by mark_rain_unknown


@dataclass
class ZoneBoundaries:
    zone_ids: list
    populations: np.ndarray
    block_groups: list[Optional[str]]
    ptr: np.ndarray  # CSR pointers into edges; zone i owns edges[ptr[i]:ptr[i+1]]
    edges: np.ndarray


@dataclass
class ZoneResult:
    zone_id: str
    block_group_geoid: Optional[str]
    population: int
    first_isolated_at: Optional[datetime]
    reconnected_at: Optional[datetime]
    isolated_steps: int
    state_at_isolation: Optional[str]  # "stranded" | "submerged"
    coverage: str  # "evaluated" | "not connected at base flow" | "no boundary roads"


@dataclass
class ZoneStatus:
    """A zone's isolation status across the optimistic and pessimistic bounds."""
    zone_id: str
    block_group_geoid: Optional[str]
    population: int
    # "reachable" | "isolated" | "possibly isolated" | "not connected at base flow" | "no boundary roads"
    status: str
    isolated_at: Optional[datetime]  # confirmed: isolated even with unknown roads passable
    earliest_possible_isolation_at: Optional[datetime]  # pessimistic bound
    state_at_isolation: Optional[str]  # "stranded" | "submerged", for confirmed isolation

    def countdown_minutes(self, now: datetime) -> Optional[int]:
        """Minutes from `now` until confirmed isolation (0 if already isolated); None otherwise."""
        if self.status != "isolated" or self.isolated_at is None:
            return None
        return max(0, int((self.isolated_at - now).total_seconds() // 60))


@dataclass
class BoundedRun:
    optimistic: "IsolationRun"
    pessimistic: "IsolationRun"
    zones: list[ZoneStatus] = field(repr=False)


@dataclass
class IsolationRun:
    drivers: tuple[str, ...]
    times: list[datetime]
    flooded_edges: np.ndarray  # (time,) count
    isolated_zones: np.ndarray  # (time,) count
    isolated_population: np.ndarray  # (time,)
    stranded_zones: np.ndarray  # (time,) count
    edge_ever_flooded: np.ndarray  # bool per edge
    zones: list[ZoneResult] = field(repr=False)


def build_network(
    segments: gpd.GeoDataFrame,
    terrain: Terrain,
    catchments: np.ndarray,
    river_threshold: np.ndarray,
    river_known: np.ndarray,
) -> RoadNetwork:
    """segments: basin road segments in the terrain CRS (see street_blocks.basin_segments).
    river_threshold: raster of the river level at which each cell floods (inf: never within range).
    river_known: bool raster of where the river driver's source covers the river."""
    node_ids: dict[int, int] = {}
    u, v = [], []
    for edge_id in segments["edge_id"]:
        a, b, _ = (int(x) for x in edge_id.split("-"))
        u.append(node_ids.setdefault(a, len(node_ids)))
        v.append(node_ids.setdefault(b, len(node_ids)))

    geoms = segments.geometry.to_numpy()
    lengths = shapely.length(geoms)
    n_samples = np.maximum(2, np.ceil(lengths / SAMPLE_SPACING_M).astype(int) + 1)
    sample_edge = np.repeat(np.arange(len(geoms)), n_samples)
    # Position of each sample along its edge, from 0 to 1.
    offsets = np.arange(len(sample_edge)) - np.repeat(np.cumsum(n_samples) - n_samples, n_samples)
    fraction = offsets / np.repeat(n_samples - 1, n_samples)
    points = shapely.line_interpolate_point(geoms[sample_edge], fraction, normalized=True)
    inv = ~terrain.transform
    col, row = inv * (shapely.get_x(points), shapely.get_y(points))
    r = np.floor(row).astype(int)
    c = np.floor(col).astype(int)
    rows_n, cols_n = terrain.dem.shape
    inside = (r >= 0) & (r < rows_n) & (c >= 0) & (c < cols_n)
    rr, cc = np.clip(r, 0, rows_n - 1), np.clip(c, 0, cols_n - 1)

    def sample(raster: np.ndarray, fill):
        return np.where(inside, raster[rr, cc], fill)

    comid = sample(terrain.catchment_comid, 0)
    pos = np.searchsorted(catchments, comid)
    if len(catchments):
        pos_ok = (pos < len(catchments)) & (catchments[np.minimum(pos, len(catchments) - 1)] == comid) & (comid > 0)
    else:
        pos_ok = np.zeros(len(comid), dtype=bool)

    stage_known = sample(river_known, False)
    stage_unknown = (sample(terrain.mainstem_drain, -1) >= 0) & ~stage_known
    edge_unknown = np.bincount(sample_edge, weights=stage_unknown, minlength=len(geoms)) > 0

    return RoadNetwork(
        edge_ids=list(segments["edge_id"]),
        u=np.array(u), v=np.array(v), n_nodes=len(node_ids),
        exempt=segments["is_exempt"].to_numpy(bool),
        geometry=segments.geometry.reset_index(drop=True),
        sample_edge=sample_edge,
        sample_river_threshold=sample(river_threshold, np.inf),
        sample_hand_network=sample(terrain.hand_network, np.nan),
        sample_catchment=np.where(pos_ok, pos, -1),
        sample_stage_known=stage_known,
        sample_depression=sample(terrain.depression_depth, 0.0) >= DEPRESSION_MIN_M,
        edge_stage_unknown=edge_unknown & ~segments["is_exempt"].to_numpy(bool),
        edge_rain_unknown=np.zeros(len(geoms), dtype=bool),
    )


def zone_boundaries(zones: list[Zone], zone_geoms: gpd.GeoSeries, net: RoadNetwork) -> ZoneBoundaries:
    """Road segments that run along each zone's boundary. zone_geoms are in the network's CRS."""
    tree = STRtree(list(net.geometry))
    ptr, edges = [0], []
    for geom in zone_geoms:
        ring = geom.boundary.buffer(BOUNDARY_TOLERANCE_M)
        for i in tree.query(ring, predicate="intersects"):
            edge = net.geometry.iloc[i]
            if edge.intersection(ring).length >= min(0.5 * edge.length, 5.0):
                edges.append(int(i))
        ptr.append(len(edges))
    return ZoneBoundaries(
        zone_ids=[z.id for z in zones],
        populations=np.array([z.population_count for z in zones]),
        block_groups=[z.block_group_geoid for z in zones],
        ptr=np.array(ptr),
        edges=np.array(edges, dtype=int),
    )


def _river_samples(net: RoadNetwork, river_level: float) -> np.ndarray:
    """Samples the river driver has under water at this river level."""
    return net.sample_stage_known & (net.sample_river_threshold <= river_level)


def _rain_samples(net: RoadNetwork, ponding_level_m: np.ndarray, river_level: float) -> tuple[np.ndarray, np.ndarray]:
    """(wet, unknown) per sample under the rain driver.

    Ponded water cannot stand above the water level of the channel it spills into: it flows there
    overland. Where the river driver covers the river, that means a sample outside a closed
    depression ponds only where the river is already there. Elsewhere (tributaries, unmapped
    mainstem) the receiving level is unmeasured, so only closed depressions, which hold water
    whatever the receiving level, count as wet; other samples below the catchment's ponding level
    are unknown.
    """
    has_catchment = net.sample_catchment >= 0
    level = np.where(has_catchment, ponding_level_m[np.maximum(net.sample_catchment, 0)], -np.inf)
    with np.errstate(invalid="ignore"):
        below = has_catchment & (net.sample_hand_network <= level)
    wet = below & (net.sample_depression | _river_samples(net, river_level))
    unknown = below & ~net.sample_depression & ~net.sample_stage_known
    return wet, unknown


def flooded_edges(
    net: RoadNetwork,
    river_level: Optional[float],
    ponding_level_m: Optional[np.ndarray],
    receiving_level: Optional[float] = None,
) -> np.ndarray:
    """Flooded segments. The river driver runs when river_level is given; the rain driver when
    ponding_level_m is given, capped by the river at receiving_level (defaults to river_level)."""
    wet = np.zeros(len(net.sample_edge), dtype=bool)
    if river_level is not None:
        wet |= _river_samples(net, river_level)
    if ponding_level_m is not None:
        receiving = river_level if receiving_level is None else receiving_level
        wet |= _rain_samples(net, ponding_level_m, receiving)[0]
    counts = np.bincount(net.sample_edge, weights=wet, minlength=len(net.u))
    return (counts >= MIN_WET_SAMPLES) & ~net.exempt


def mark_rain_unknown(net: RoadNetwork, river_level: np.ndarray, ponding_level_m: np.ndarray) -> None:
    """Flag segments that, at any timestep, would pond beyond closed depressions toward an unmeasured
    receiving water level. Their flooding is unknown; they are handled like stage-unknown segments."""
    ever = np.zeros(len(net.u), dtype=bool)
    for t in range(len(river_level)):
        _, unknown = _rain_samples(net, ponding_level_m[t], river_level[t])
        ever |= np.bincount(net.sample_edge, weights=unknown, minlength=len(net.u)) >= MIN_WET_SAMPLES
    net.edge_rain_unknown = ever & ~net.exempt


class BaseFlowFloodingError(AssertionError):
    """Roads flood at a timestep where the river is at base flow: the flood model is wrong, not the event."""


def assert_dry_at_base_flow(
    net: RoadNetwork, river_level: float, ponding_level_m: Optional[np.ndarray], when: str
) -> None:
    """Fail loudly if any road segment floods, under any driver in use, at a base-flow timestep."""
    problems = []
    checks = [("river", flooded_edges(net, river_level, None))]
    if ponding_level_m is not None:
        checks.append(("rain", flooded_edges(net, None, ponding_level_m, river_level)))
    for driver, flooded in checks:
        idx = np.flatnonzero(flooded)
        if len(idx):
            sample = ", ".join(net.edge_ids[i] for i in idx[:10])
            problems.append(f"{driver} driver floods {len(idx)} segments (e.g. {sample})")
    if problems:
        raise BaseFlowFloodingError(
            f"Base-flow check failed at {when} (river level {river_level}): " + "; ".join(problems)
        )


def run_isolation(
    net: RoadNetwork,
    zones: ZoneBoundaries,
    times: list[datetime],
    river_level: np.ndarray,
    ponding_level_m: Optional[np.ndarray],
    drivers: tuple[str, ...] = ("stage",),
    unknown_blocked: Optional[np.ndarray] = None,
) -> IsolationRun:
    """One isolation run. Roads whose flooding is unknown are passable, except at timesteps where
    unknown_blocked[t] is True, when they are treated as flooded (the pessimistic bound)."""
    if "rain" in drivers and not RAIN_DRIVER_VALIDATED:
        raise UnvalidatedDriverError("The rain driver is not validated; it produces no isolation output")
    n_zones = len(zones.zone_ids)
    has_boundary = np.diff(zones.ptr) > 0
    starts = np.minimum(zones.ptr[:-1], max(len(zones.edges) - 1, 0))
    edge_unknown = net.edge_stage_unknown | net.edge_rain_unknown

    # Zones already cut off from the main network with every road dry are disconnected by the road
    # network itself (fragments, basin-boundary cuts), not by flooding.
    _, base_labels = connected_components(
        coo_matrix((np.ones(len(net.u)), (net.u, net.v)), shape=(net.n_nodes, net.n_nodes)), directed=False
    )
    base_ok = base_labels[net.u] == np.bincount(base_labels).argmax()
    connected_at_base = (
        np.logical_or.reduceat(base_ok[zones.edges], starts) & has_boundary
        if len(zones.edges) else np.zeros(n_zones, bool)
    )
    evaluated = has_boundary & connected_at_base
    isolated_hist = np.zeros((len(times), n_zones), dtype=bool)
    stranded_hist = np.zeros((len(times), n_zones), dtype=bool)
    flooded_count = np.zeros(len(times), dtype=int)
    ever = np.zeros(len(net.u), dtype=bool)

    for t in range(len(times)):
        flooded = flooded_edges(
            net,
            river_level[t] if "stage" in drivers else None,
            ponding_level_m[t] if "rain" in drivers else None,
            receiving_level=river_level[t],
        )
        ever |= flooded
        if unknown_blocked is not None and unknown_blocked[t]:
            flooded = flooded | edge_unknown
        flooded_count[t] = int(flooded.sum())
        keep = ~flooded
        graph = coo_matrix(
            (np.ones(int(keep.sum())), (net.u[keep], net.v[keep])), shape=(net.n_nodes, net.n_nodes)
        )
        _, labels = connected_components(graph, directed=False)
        main = np.bincount(labels).argmax()
        edge_ok = keep & (labels[net.u] == main)

        ok = np.logical_or.reduceat(edge_ok[zones.edges], starts) if len(zones.edges) else np.zeros(n_zones, bool)
        dry = np.logical_or.reduceat(keep[zones.edges], starts) if len(zones.edges) else np.zeros(n_zones, bool)
        isolated_hist[t] = evaluated & ~ok
        stranded_hist[t] = isolated_hist[t] & dry

    results = []
    for i in range(n_zones):
        if not evaluated[i]:
            results.append(ZoneResult(
                zone_id=str(zones.zone_ids[i]), block_group_geoid=zones.block_groups[i],
                population=int(zones.populations[i]), first_isolated_at=None, reconnected_at=None,
                isolated_steps=0, state_at_isolation=None,
                coverage="no boundary roads" if not has_boundary[i] else "not connected at base flow",
            ))
            continue
        steps = np.flatnonzero(isolated_hist[:, i])
        first = int(steps[0]) if len(steps) else None
        back = None
        if first is not None:
            after = np.flatnonzero(~isolated_hist[first:, i])
            back = first + int(after[0]) if len(after) else None
        results.append(ZoneResult(
            zone_id=str(zones.zone_ids[i]),
            block_group_geoid=zones.block_groups[i],
            population=int(zones.populations[i]),
            first_isolated_at=times[first] if first is not None else None,
            reconnected_at=times[back] if back is not None else None,
            isolated_steps=len(steps),
            state_at_isolation=None if first is None else ("stranded" if stranded_hist[first, i] else "submerged"),
            coverage="evaluated",
        ))
    return IsolationRun(
        drivers=drivers,
        times=times,
        flooded_edges=flooded_count,
        isolated_zones=isolated_hist.sum(axis=1),
        isolated_population=(isolated_hist * zones.populations).sum(axis=1),
        stranded_zones=stranded_hist.sum(axis=1),
        edge_ever_flooded=ever,
        zones=results,
    )


def run_bounded(
    net: RoadNetwork,
    zones: ZoneBoundaries,
    times: list[datetime],
    river_level: np.ndarray,
    unknown_blocked: np.ndarray,
) -> BoundedRun:
    """Bounded reachability for the river driver.

    Optimistic: roads with unknown flooding are passable. Pessimistic: they are impassable while
    unknown_blocked[t] (the gauge is at/above minor flood stage). A zone is "isolated" if it is
    isolated even in the optimistic run (confirmed), "possibly isolated" if only in the pessimistic
    run, and "reachable" if in neither.
    """
    optimistic = run_isolation(net, zones, times, river_level, None, ("stage",))
    pessimistic = run_isolation(net, zones, times, river_level, None, ("stage",), unknown_blocked=unknown_blocked)
    statuses = []
    for opt, pes in zip(optimistic.zones, pessimistic.zones):
        if opt.coverage != "evaluated":
            status = opt.coverage
        elif opt.first_isolated_at is not None:
            status = "isolated"
        elif pes.first_isolated_at is not None:
            status = "possibly isolated"
        else:
            status = "reachable"
        firsts = [t for t in (opt.first_isolated_at, pes.first_isolated_at) if t is not None]
        statuses.append(ZoneStatus(
            zone_id=opt.zone_id, block_group_geoid=opt.block_group_geoid, population=opt.population,
            status=status, isolated_at=opt.first_isolated_at,
            earliest_possible_isolation_at=min(firsts) if firsts else None,
            state_at_isolation=opt.state_at_isolation,
        ))
    return BoundedRun(optimistic=optimistic, pessimistic=pessimistic, zones=statuses)


def update_zone_countdowns(
    db: Session, bounded: BoundedRun, now: datetime, gauge_site_id: str, river_driver_caveat: Optional[str] = None
) -> None:
    """Write each zone's countdown to confirmed isolation, as of `now`, to zones.isolation_minutes, and
    record in zones.coverage_gaps why a zone has no countdown (possibly isolated, not evaluated).
    river_driver_caveat, if given, is also recorded (e.g. a lower-confidence river driver)."""
    by_id = {z.zone_id: z for z in bounded.zones}
    for zone in db.query(Zone).filter(Zone.id.in_(list(by_id))):
        result = by_id[str(zone.id)]
        zone.isolation_minutes = result.countdown_minutes(now)
        gaps = {}
        if result.status == "possibly isolated":
            gaps["isolation"] = {
                "status": "possibly isolated",
                "earliest_possible_isolation_at": result.earliest_possible_isolation_at.isoformat(),
                "reason": (
                    f"Isolated only if roads whose flooding is unknown are flooded: they drain to a stretch of "
                    f"river outside what USGS {gauge_site_id}'s flood source covers (the NWS map's mapped "
                    f"extent, or the gauge's own reach for HAND). Treated as impassable while the gauge is at "
                    f"or above minor flood stage."),
            }
        elif result.status == "not connected at base flow":
            gaps["isolation"] = (
                "This block's roads do not connect to the main road network even with every road dry "
                "(network fragment or basin-boundary cut); isolation by flooding not evaluated.")
        elif result.status == "no boundary roads":
            gaps["isolation"] = "No drivable road borders this block; isolation not evaluated."
        if river_driver_caveat and result.status in ("reachable", "isolated", "possibly isolated"):
            gaps["river_driver"] = river_driver_caveat
        zone.coverage_gaps = gaps or None
    db.commit()
