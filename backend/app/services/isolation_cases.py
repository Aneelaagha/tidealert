"""Isolation-engine pieces of a Case: the mechanism behind a confirmed isolation, its confidence, and cleanup.

Cases themselves are opened and updated by the case matcher
(app.services.case_matcher), one sweep at a time. The mechanism is what the
engine found at the isolation timestep:

- "stranded": some of the block's own roads are still dry, but every road
  leading out of the dry pocket they belong to is flooded (the exit roads);
- "submerged": every road bordering the block is flooded.

Confidence of an isolation contribution (isolation_confidence) is the
product of four factors, each from data the engine already has:

    coverage         share of the roads that cut the block off (exit roads, or boundary roads if
                     submerged) flooded by sample points the river driver covers (>= MIN_WET_SAMPLES).
                     For a confirmed isolation every cut road is flooded that way by construction, so
                     this is 1.0 for every current case; it only matters if cases are ever opened from
                     the pessimistic bound, where unknown roads count as cut
    source_agreement 1.0 for an NWS flood-map library; for HAND, its agreement with NWS maps (median
                     IoU over flooding timesteps) measured at gauges that have both, borrowed
    stage_provenance 1.0 when the gauge measured stage at that timestep, RECONSTRUCTED_STAGE_FACTOR when
                     it was reconstructed from (estimated) discharge through the rating curve
    library_range    1.0 within the NWS library's mapped stages, ABOVE_LIBRARY_FACTOR above its highest

RECONSTRUCTED_STAGE_FACTOR and ABOVE_LIBRARY_FACTOR are unvalidated design
choices. The whole score is a heuristic built from measured inputs, not a
probability calibrated against case outcomes.
"""
import glob
import json
import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Case
from app.services.isolation_engine import MIN_WET_SAMPLES, RoadNetwork, ZoneBoundaries, flooded_edges

log = logging.getLogger(__name__)

RECONSTRUCTED_STAGE_FACTOR = 0.7  # GUESS
ABOVE_LIBRARY_FACTOR = 0.7  # GUESS
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


@dataclass
class Mechanism:
    state: str  # "stranded" | "submerged"
    boundary_roads: int
    dry_boundary_roads: int
    exit_roads_flooded: int
    exit_road_classes: dict[str, int]
    cut_edges: np.ndarray = field(repr=False)  # the roads that cut the block off


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
        return Mechanism("submerged", len(edges), 0, 0, {}, cut_edges=edges)
    pocket = set(labels[net.u[dry]]) | set(labels[net.v[dry]])
    in_u, in_v = np.isin(labels[net.u], list(pocket)), np.isin(labels[net.v], list(pocket))
    exits = np.flatnonzero(flooded & (in_u ^ in_v))
    return Mechanism(
        state="stranded",
        boundary_roads=len(edges),
        dry_boundary_roads=len(dry),
        exit_roads_flooded=len(exits),
        exit_road_classes=dict(Counter(highway_class[e] for e in exits)),
        cut_edges=exits,
    )


_hand_prior: Optional[tuple[float, str]] = None


def hand_agreement_prior() -> tuple[float, str]:
    """(agreement, provenance) for HAND at gauges without an NWS map: the mean of the median HAND-vs-NWS
    IoU measured at gauges that have both, from their latest pipeline reports."""
    global _hand_prior
    if _hand_prior is None:
        values = {}
        for path in glob.glob(os.path.join(DATA_DIR, "usgs-*", "backtest.json")):
            with open(path) as f:
                median = (json.load(f).get("hand_vs_nws_iou") or {}).get("event_steps_median")
            if median is not None:
                values[os.path.basename(os.path.dirname(path))] = median
        if values:
            _hand_prior = (float(np.mean(list(values.values()))),
                           "borrowed from " + ", ".join(f"{k} {v:.2f}" for k, v in sorted(values.items())))
        else:
            log.warning("No HAND-vs-NWS agreement measured at any gauge; FALLBACK source agreement 0.5")
            _hand_prior = (0.5, "FALLBACK 0.5: no gauge with both HAND and an NWS map has been run")
    return _hand_prior


@dataclass
class IsolationConfidence:
    value: float
    coverage: float
    source_agreement: float
    stage_provenance: float
    library_range: float
    source_note: str

    def describe(self) -> str:
        return (f"confidence {self.value:.2f} = coverage {self.coverage:.2f} x source {self.source_agreement:.2f} "
                f"({self.source_note}) x stage {self.stage_provenance:.2f} x range {self.library_range:.2f}")


def isolation_confidence(net: RoadNetwork, river_confidence: str, stage_provenance: str, stage_ft: float,
                         library_max_ft: Optional[float], mech: Optional[Mechanism],
                         river_level: Optional[float] = None) -> IsolationConfidence:
    """Confidence of an isolation contribution. mech=None (e.g. a reconnection) skips the coverage factor."""
    if mech is not None and len(mech.cut_edges) and river_level is not None:
        covered_wet = net.sample_stage_known & (net.sample_river_threshold <= river_level)
        wet_counts = np.bincount(net.sample_edge, weights=covered_wet, minlength=len(net.u))
        coverage = float(np.mean(wet_counts[mech.cut_edges] >= MIN_WET_SAMPLES))
    else:
        coverage = 1.0
    if river_confidence == "primary":
        source, note = 1.0, "NWS flood map"
    else:
        source, note = hand_agreement_prior()
        note = f"HAND, {note}"
    provenance = 1.0 if stage_provenance == "observed" else RECONSTRUCTED_STAGE_FACTOR
    in_range = 1.0 if library_max_ft is None or stage_ft <= library_max_ft else ABOVE_LIBRARY_FACTOR
    return IsolationConfidence(coverage * source * provenance * in_range, coverage, source, provenance, in_range, note)


def clear_cases(db: Session, source: str) -> int:
    """Delete every case from one source, with its contributions and tasks, e.g. before a replay is rerun."""
    old = list(db.scalars(select(Case).where(Case.source == source)))
    for case in old:
        case.task = None  # cases.task_id -> tasks and tasks.case_id -> cases form a cycle: break it first
    db.flush()
    for case in old:
        for task in list(case.tasks):
            db.delete(task)  # task events cascade
    db.flush()
    for case in old:
        db.delete(case)  # contributions cascade
    db.flush()
    return len(old)
