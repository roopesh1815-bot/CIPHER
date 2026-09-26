"""
CIPHER API — Graph data endpoint.
Serves output/graph.json (produced by pipeline/graph/exporter.py) to the
frontend, with optional filtering so a judge/investigator isn't forced to
render all 2,957 nodes at once if they just want one community or entity type.
"""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from api.security import get_current_user

from core.db import fetch_all
from core.spiderweb_center import build_spiderweb_center

router = APIRouter(prefix="/api/graph", tags=["graph"])

GRAPH_JSON_PATH = Path("output/graph.json")

_graph_cache: dict | None = None


def _load_graph() -> dict:
    """Load output/graph.json once and cache in memory — it only changes when
    run_pipeline.py is re-run, not on every request."""
    global _graph_cache
    if _graph_cache is None:
        if not GRAPH_JSON_PATH.exists():
            raise HTTPException(status_code=404, detail="graph.json not found — run run_pipeline.py first")
        with open(GRAPH_JSON_PATH) as f:
            _graph_cache = json.load(f)
    return _graph_cache


@router.get("")
def get_graph(
    user: dict = Depends(get_current_user),
    community: int | None = Query(None, description="Filter to one community/gang ID"),
    entity_type: str | None = Query(None, description="Filter to one entity type, e.g. Account, Person"),
    search: str | None = Query(None, description="Case-insensitive substring match on node label"),
    limit: int | None = Query(None, ge=1, le=5000, description="Cap number of nodes returned, largest first"),
):
    """
    Returns {nodes, edges, meta} shaped for vis-network. Edges are always
    filtered down to only those whose both endpoints survive the node filters,
    so the graph never shows a dangling edge to a node that isn't displayed.
    """
    data = _load_graph()
    nodes = data["nodes"]
    edges = data["edges"]

    if community is not None:
        nodes = [n for n in nodes if n.get("community") == community]
    if entity_type is not None:
        nodes = [n for n in nodes if n.get("entity_type", "").lower() == entity_type.lower()]
    if search:
        s = search.lower()
        nodes = [n for n in nodes if s in n.get("label", "").lower()]

    if limit is not None and len(nodes) > limit:
        nodes = sorted(nodes, key=lambda n: n.get("size", 0), reverse=True)[:limit]

    node_ids = {n["id"] for n in nodes}
    edges = [e for e in edges if e["source"] in node_ids and e["target"] in node_ids]

    # vis-network expects "from"/"to", not "source"/"target"
    vis_edges = [
        {
            "from": e["source"],
            "to": e["target"],
            "title": e.get("rel_type", ""),
            "value": e.get("weight", 1),
        }
        for e in edges
    ]

    return {
        "nodes": nodes,
        "edges": vis_edges,
        "meta": {"node_count": len(nodes), "edge_count": len(vis_edges), "full_meta": data.get("meta", {})},
    }


@router.get("/entity-types")
def get_entity_types(user: dict = Depends(get_current_user)):
    """Distinct entity types present in the graph, for populating a filter dropdown."""
    data = _load_graph()
    types = sorted({n.get("entity_type", "Unknown") for n in data["nodes"]})
    return {"entity_types": types}


@router.get("/{node_id}")
def get_node_detail(node_id: str, user: dict = Depends(get_current_user)):
    """Full attributes for one node, plus its immediate neighbours — used by
    the side panel when a user clicks a node in the graph."""
    data = _load_graph()
    node = next((n for n in data["nodes"] if n["id"] == node_id), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

    neighbor_edges = [e for e in data["edges"] if e["source"] == node_id or e["target"] == node_id]
    neighbor_ids = {e["target"] if e["source"] == node_id else e["source"] for e in neighbor_edges}
    neighbors = [n for n in data["nodes"] if n["id"] in neighbor_ids]

    return {"node": node, "neighbors": neighbors, "edges": neighbor_edges}
    # add to the existing imports at the top of api/routers/graph.py
from core.db import fetch_all


@router.get("/case/{fir_id}")
def get_case_graph(
    fir_id: str,
    user: dict = Depends(get_current_user),
    hops: int = Query(1, ge=1, le=2, description="How many hops out from the case's own entities to expand"),
):
    """
    Case-scoped ego-graph: seeds from this case's case_entities (matched
    to graph nodes by label), then expands `hops` steps outward through
    the existing global graph. This is a lens on the same graph.json data
    used by the main network graph page — not a separate graph build.

    Returns the same {nodes, edges, meta} shape as GET /api/graph, plus a
    `seed_count` in meta showing how many of the case's own entities were
    actually found in the graph (some case_entities — e.g. locations —
    may not exist as graph nodes, which is expected, not an error).
    """
    data = _load_graph()
    all_nodes = {n["id"]: n for n in data["nodes"]}
    all_edges = data["edges"]

    case_entities = fetch_all(
        "SELECT entity_label FROM case_entities WHERE fir_id = ?", (fir_id,)
    )
    if not case_entities:
        raise HTTPException(status_code=404, detail=f"No entities found for case {fir_id}")

    # Match case_entities rows to graph nodes by label — the graph's own
    # ids (ACC-, PER-, etc.) aren't stored in case_entities, so label is
    # the reliable join key available here.
    labels = {e["entity_label"] for e in case_entities}
    seed_ids = {n["id"] for n in data["nodes"] if n.get("label") in labels}

    if not seed_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Case {fir_id} has entities on file, but none matched a node in the graph.",
        )

    # Build adjacency once for BFS expansion.
    adjacency: dict[str, set[str]] = {}
    for e in all_edges:
        adjacency.setdefault(e["source"], set()).add(e["target"])
        adjacency.setdefault(e["target"], set()).add(e["source"])

    frontier = set(seed_ids)
    visited = set(seed_ids)
    for _ in range(hops):
        next_frontier = set()
        for node_id in frontier:
            next_frontier |= adjacency.get(node_id, set())
        next_frontier -= visited
        visited |= next_frontier
        frontier = next_frontier

    nodes = [all_nodes[nid] for nid in visited if nid in all_nodes]
    node_ids = {n["id"] for n in nodes}
    edges = [e for e in all_edges if e["source"] in node_ids and e["target"] in node_ids]

    # Mark which nodes are the case's own entities vs. expanded neighbours,
    # so the frontend can visually distinguish "this case" from "context".
        # Mark which nodes are the case's own entities vs. expanded neighbours,
    # so the frontend can visually distinguish "this case" from "context".
    for n in nodes:
        n["is_case_entity"] = n["id"] in seed_ids

    vis_edges = [
        {
            "from": e["source"],
            "to": e["target"],
            "title": e.get("rel_type", ""),
            "value": e.get("weight", 1),
        }
        for e in edges
    ]

    # Spider-web view: collapse multi-suspect seeds into one merged center,
    # rewire/dedupe edges. Falls back to the best-fused case entity if no
    # seed is tagged "Suspect".
    center_result = build_spiderweb_center(nodes, vis_edges)
    other_nodes = [n for n in nodes if n["id"] not in center_result.merged_member_ids]
    final_nodes = [center_result.center_node] + other_nodes

    return {
        "nodes": final_nodes,
        "edges": center_result.edges,
        "internal_links": center_result.internal_links,
        "center_reason": center_result.center_reason,
        "meta": {
            "fir_id": fir_id,
            "seed_count": len(seed_ids),
            "hops": hops,
            "node_count": len(final_nodes),
            "edge_count": len(center_result.edges),
        },
    }