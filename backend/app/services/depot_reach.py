"""Depot access: can a supply run starting at a depot reach a zone by a dry road route? Feasibility only.

This reuses the isolation engine's own machinery (app.services.isolation_engine): the same flooded-road test
(`flooded_edges`), the same optimistic and pessimistic treatment of roads whose flooding is unknown, and the same
connected-components test. The one difference is the question. The engine asks "can this zone reach the main road
network?"; here the "main network" is the part of the road network the depot's road belongs to at that time step, so
"can the depot's road reach one of this zone's boundary roads over roads that are dry?".

What it is not: no route is found or returned, nothing is optimised, and no distance, time, vehicle or road capacity is
involved. A zone is "reachable" when a dry route exists, not when a vehicle could use it (debris, damage and closures
are not modelled). The existing isolation_engine code is not changed.

States per zone and time step, for one depot:
- 3 reachable: a dry route exists even if every road of unknown flooding is flooded (the pessimistic bound).
- 2 only if unknown roads are passable: reachable in the optimistic run, not in the pessimistic one.
- 1 not reachable: no dry route even with unknown roads passable (the depot's roads and the zone's are cut apart, or the
  depot's own road is flooded).
- 0 not evaluated: the engine could not evaluate the zone (see isolation_engine.evaluated_zones).
"""
from typing import Optional

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from shapely.geometry import Point
from shapely.strtree import STRtree

from app.services import isolation_engine as engine

NOT_EVALUATED, NOT_REACHABLE, ONLY_IF_UNKNOWN_PASSABLE, REACHABLE = 0, 1, 2, 3
STATE_NAMES = {NOT_EVALUATED: "not_evaluated", NOT_REACHABLE: "not_reachable",
               ONLY_IF_UNKNOWN_PASSABLE: "only_if_unknown_roads_passable", REACHABLE: "reachable"}
MAX_SNAP_M = 150.0  # a depot farther than this from a modelled road is not evaluated


def snap_to_road(net: engine.RoadNetwork, x: float, y: float) -> tuple[int, float]:
    """The nearest road segment to a point in the network's CRS, and its distance in metres."""
    geoms = list(net.geometry)
    tree = STRtree(geoms)
    i = int(tree.nearest(Point(x, y)))
    return i, float(geoms[i].distance(Point(x, y)))


def _reach(net: engine.RoadNetwork, zones: engine.ZoneBoundaries, river_level: Optional[float], unknown_blocked: bool,
           depot_edge: int) -> tuple[bool, np.ndarray]:
    """(is the depot's road dry, which zones have a dry boundary road in the depot's component) at one step."""
    flooded = engine.flooded_edges(net, river_level, None, receiving_level=river_level)
    if unknown_blocked:
        flooded = flooded | net.edge_stage_unknown | net.edge_rain_unknown
    keep = ~flooded
    n_zones = len(zones.zone_ids)
    if not keep[depot_edge]:  # the depot's own road is under water: nothing leaves it
        return False, np.zeros(n_zones, bool)
    graph = coo_matrix((np.ones(int(keep.sum())), (net.u[keep], net.v[keep])), shape=(net.n_nodes, net.n_nodes))
    _, labels = connected_components(graph, directed=False)
    edge_ok = keep & (labels[net.u] == labels[net.u[depot_edge]])
    if not len(zones.edges):
        return True, np.zeros(n_zones, bool)
    starts = np.minimum(zones.ptr[:-1], len(zones.edges) - 1)
    return True, np.logical_or.reduceat(edge_ok[zones.edges], starts)


def zone_states(net: engine.RoadNetwork, zones: engine.ZoneBoundaries, evaluated: np.ndarray,
                river_level: Optional[float], unknown_blocked: bool, depot_edge: int) -> tuple[np.ndarray, bool]:
    """One depot's state for every zone at one time step, and whether the depot's own road is dry (optimistic run)."""
    dry_opt, opt = _reach(net, zones, river_level, False, depot_edge)
    _, pess = _reach(net, zones, river_level, unknown_blocked, depot_edge)
    states = np.full(len(zones.zone_ids), NOT_REACHABLE, dtype=np.uint8)
    states[opt] = ONLY_IF_UNKNOWN_PASSABLE
    states[pess] = REACHABLE
    states[~evaluated] = NOT_EVALUATED
    return states, dry_opt


def in_main_network(net: engine.RoadNetwork, river_level: Optional[float], depot_edge: int) -> bool:
    """Is the depot's road in the same part of the network as the engine's main network (the largest component), with
    unknown roads passable? Where it is, 'not reachable' from the depot equals the engine's own 'isolated'."""
    flooded = engine.flooded_edges(net, river_level, None, receiving_level=river_level)
    keep = ~flooded
    if not keep[depot_edge]:
        return False
    graph = coo_matrix((np.ones(int(keep.sum())), (net.u[keep], net.v[keep])), shape=(net.n_nodes, net.n_nodes))
    _, labels = connected_components(graph, directed=False)
    return bool(labels[net.u[depot_edge]] == np.bincount(labels).argmax())
