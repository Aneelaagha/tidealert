"""Open Cases for zones the isolation engine confirms are isolated.

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
from datetime import datetime, tzinfo
from typing import Optional

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Case, CaseEngineContribution
from app.models.case import CaseStatus, ConfidenceWord
from app.models.case_engine_contribution import Engine
from app.services.isolation_engine import BoundedRun, RoadNetwork, ZoneBoundaries, flooded_edges

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


def write_isolation_cases(
    db: Session,
    *,
    source: str,
    bounded: BoundedRun,
    net: RoadNetwork,
    bounds: ZoneBoundaries,
    highway_class: list[str],
    times: list[datetime],
    river_level: np.ndarray,
    river_method: str,
    river_confidence: str,
    river_units: str,
    stage_ft: np.ndarray,
    site_id: str,
    local_tz: tzinfo,
    zone_ids: Optional[list] = None,
) -> list[Case]:
    """Replace this source's cases with one per confirmed-isolated zone; return the new cases."""
    clear_cases(db, source)

    index = {str(z): i for i, z in enumerate(zone_ids if zone_ids is not None else bounds.zone_ids)}
    cases = []
    for status in bounded.zones:
        if status.status != "isolated":
            continue
        i = times.index(status.isolated_at)
        k = index[status.zone_id]
        mech = isolation_mechanism(net, bounds, k, float(river_level[i]), highway_class)
        when = status.isolated_at.astimezone(local_tz).strftime("%Y-%m-%d %H:%M %Z")
        level = f"{river_level[i]:.1f} {river_units}"
        if mech.state == "stranded":
            classes = ", ".join(f"{n} {c}" for c, n in sorted(mech.exit_road_classes.items()))
            dry = (f"all {mech.boundary_roads}" if mech.dry_boundary_roads == mech.boundary_roads else
                   f"{mech.dry_boundary_roads} of its {mech.boundary_roads}")
            exits = {1: "the only road", 2: "both roads"}.get(mech.exit_roads_flooded,
                                                              f"all {mech.exit_roads_flooded} roads")
            how = (f"{dry} boundary roads stayed dry, but {exits} leading out of its "
                   f"neighborhood flooded")
            fragment = (f"stranded: {mech.dry_boundary_roads}/{mech.boundary_roads} boundary roads dry; "
                        f"{mech.exit_roads_flooded} exit roads flooded ({classes}); river level {level} at "
                        f"stage {stage_ft[i]:.2f} ft; {river_method}; confirmed with unknown roads passable")
        else:
            how = ("its only boundary road flooded" if mech.boundary_roads == 1 else
                   f"all {mech.boundary_roads} of its boundary roads flooded")
            fragment = (f"submerged: {mech.boundary_roads}/{mech.boundary_roads} boundary roads flooded; river "
                        f"level {level} at stage {stage_ft[i]:.2f} ft; {river_method}; confirmed with unknown "
                        f"roads passable")
        caveat = " (lower-confidence HAND river model)" if river_confidence != "primary" else ""
        sentence = (f"Street block with {status.population} residents was cut off from the main road network at "
                    f"{when}: {how}, with USGS {site_id} at {stage_ft[i]:.2f} ft{caveat}.")
        case = Case(
            zone_id=bounds.zone_ids[k],
            status=CaseStatus.open,
            inference_sentence=sentence,
            confidence_word=ConfidenceWord.single_source,
            source=source,
            opened_at=status.isolated_at,
            last_contribution_at=status.isolated_at,
        )
        case.contributions.append(CaseEngineContribution(
            engine=Engine.isolation,
            rule_fragment=fragment,
            engine_confidence=ENGINE_CONFIDENCE[river_confidence],
        ))
        db.add(case)
        cases.append(case)
    db.commit()
    return cases
