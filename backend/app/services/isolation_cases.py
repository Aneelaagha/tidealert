"""Isolation-engine pieces of a Case: the mechanism behind a confirmed isolation, and case cleanup.

Cases themselves are opened and updated by the case matcher
(app.services.case_matcher), one sweep at a time.

One Case per zone whose bounded-reachability status is "isolated" (isolated
even with every road of unknown status passable), plus one
CaseEngineContribution from the isolation engine describing the mechanism it
actually found at the isolation timestep:

- "stranded": some of the block's own roads are still dry, but every road
  leading out of the dry pocket they belong to is flooded (the exit roads);
- "submerged": every road bordering the block is flooded.

Cases from a historical replay carry a `source` label and their historical
opened_at, and are replaced wholesale on every run of the same source, so
they never mix with, or duplicate, live cases.

engine_confidence is an ORDINAL tier, not a calibrated probability: nothing
has yet been checked against case outcomes. Confirmed isolation from the NWS
flood-map river driver ranks above the lower-confidence HAND driver.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Case
from app.services.isolation_engine import RoadNetwork, ZoneBoundaries, flooded_edges

# Ordinal tiers, uncalibrated: see the module docstring.
ENGINE_CONFIDENCE = {"primary": 0.8, "LOWER CONFIDENCE": 0.4}


@dataclass
class Mechanism:
    state: str  # "stranded" | "submerged"
    boundary_roads: int
    dry_boundary_roads: int
    exit_roads_flooded: int
    exit_road_classes: dict[str, int]


def isolation_mechanism(
    net: RoadNetwork, bounds: ZoneBoundaries, zone_index: int, river_level: float, highway_class: list[str]
) -> Mechanism:
    """Recompute the known flood state at one timestep and describe how this zone is cut off."""
    flooded = flooded_edges(net, river_level, None)
    keep = ~flooded
    graph = coo_matrix((np.ones(int(keep.sum())), (net.u[keep], net.v[keep])), shape=(net.n_nodes, net.n_nodes))
    _, labels = connected_components(graph, directed=False)

    edges = bounds.edges[bounds.ptr[zone_index]:bounds.ptr[zone_index + 1]]
    dry = edges[keep[edges]]
    if len(dry) == 0:
        return Mechanism("submerged", len(edges), 0, 0, {})
    pocket = set(labels[net.u[dry]]) | set(labels[net.v[dry]])
    in_u, in_v = np.isin(labels[net.u], list(pocket)), np.isin(labels[net.v], list(pocket))
    exits = np.flatnonzero(flooded & (in_u ^ in_v))
    return Mechanism(
        state="stranded",
        boundary_roads=len(edges),
        dry_boundary_roads=len(dry),
        exit_roads_flooded=len(exits),
        exit_road_classes=dict(Counter(highway_class[e] for e in exits)),
    )


def clear_cases(db: Session, source: str) -> int:
    """Delete every case (and its contributions) from one source, e.g. before a replay is rerun."""
    old = list(db.scalars(select(Case).where(Case.source == source)))
    for case in old:
        db.delete(case)  # contributions cascade
    db.flush()
    return len(old)
