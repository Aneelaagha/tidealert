"""Load the OpenStreetMap drivable road network around White Oak Bayou into road_segments.

Pulls the unsimplified OSM drive network with osmnx, then simplifies it without
merging across OSM ways or across bridge/tunnel boundaries, so every stored
segment belongs to exactly one OSM way and has a single bridge/tunnel value.
The graph is made undirected: for isolation, what matters is whether a
rescue vehicle can physically traverse a segment, not the one-way rules.

graph_edge_id is "<u>-<v>-<key>" (OSM node ids), which the isolation engine
uses to rebuild the graph from the database.

The query is pinned to OSM_DATE via Overpass's historical ("attic") data so the
network is the one that existed when Harvey made landfall, not today's.

Usage (from the repo root):
    .venv/bin/python scripts/pull_osm_roads.py
"""
import os
import sys
import uuid

import osmnx as ox

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from geoalchemy2.shape import from_shape  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import RoadSegment  # noqa: E402

# (west, south, east, north) around USGS 08074500; contains the NWS FIM
# library extent for HGTT2 (-95.429..-95.372, 29.773..29.789).
BBOX = (-95.50, 29.74, -95.36, 29.87)

ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "tidealert:road_segments")

# Day before Harvey's landfall.
OSM_DATE = "2017-08-24T00:00:00Z"


def tag_is(value, excluded: set[str]) -> bool:
    """OSM tag present and not one of the excluded values (lists come from merged edges)."""
    values = value if isinstance(value, list) else [value]
    return any(isinstance(v, str) and v not in excluded for v in values)


def main() -> None:
    ox.settings.overpass_settings = f'[out:json][timeout:{{timeout}}]{{maxsize}}[date:"{OSM_DATE}"]'
    ox.settings.useful_tags_way = list(ox.settings.useful_tags_way) + ["bridge", "tunnel", "layer"]
    graph = ox.graph_from_bbox(BBOX, network_type="drive", simplify=False, retain_all=True)
    graph = ox.simplify_graph(graph, edge_attrs_differ=["osmid", "bridge", "tunnel"])
    graph = ox.convert.to_undirected(graph)
    edges = ox.convert.graph_to_gdfs(graph, nodes=False, fill_edge_geometry=True)
    print(f"{graph.number_of_nodes()} nodes, {len(edges)} undirected edges")

    rows = []
    for (u, v, key), edge in edges.iterrows():
        osmid = edge["osmid"][0] if isinstance(edge["osmid"], list) else edge["osmid"]
        highway = edge["highway"]
        edge_id = f"{u}-{v}-{key}"
        rows.append(
            dict(
                id=uuid.uuid5(ID_NAMESPACE, edge_id),
                osm_way_id=int(osmid),
                geometry=from_shape(edge["geometry"], srid=4326),
                highway_class=";".join(highway) if isinstance(highway, list) else highway,
                # bridge=no / tunnel=no are explicit negatives; tunnel=culvert is a
                # pipe under an at-grade road, not a road tunnel.
                is_bridge=tag_is(edge.get("bridge"), {"no"}),
                is_tunnel=tag_is(edge.get("tunnel"), {"no", "culvert"}),
                graph_edge_id=edge_id,
            )
        )

    with SessionLocal() as db:
        # The network is a snapshot: replace it wholesale.
        db.execute(delete(RoadSegment))
        db.bulk_insert_mappings(RoadSegment, rows)
        db.commit()

    n_bridge = sum(r["is_bridge"] for r in rows)
    n_tunnel = sum(r["is_tunnel"] for r in rows)
    print(f"Loaded {len(rows)} road segments as of {OSM_DATE}: {n_bridge} bridges, {n_tunnel} tunnels")


if __name__ == "__main__":
    main()
