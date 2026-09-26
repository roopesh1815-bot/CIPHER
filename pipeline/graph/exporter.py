"""
CrimeNet AI — Graph Exporter
Exports NetworkX graph to JSON (for dashboard) and GEXF (for Gephi)
"""

import json
import networkx as nx
import pandas as pd
from core.config import GRAPH_GEXF, GRAPH_JSON, RELATIONSHIPS_CSV


def export_json(G: nx.Graph, out_path: str):
    nodes, edges = [], []

    for node, data in G.nodes(data=True):
        etype  = data.get("entity_type", "Unknown")
        color_map = {
            "Person":      "#E74C3C",
            "Mobile":      "#3498DB",
            "Vehicle":     "#F39C12",
            "Account":     "#2ECC71",
            "Location":    "#9B59B6",
            "CellTower":   "#1ABC9C",
            "SocialHandle":"#E67E22",
        }
        nodes.append({
            "id":            node,
            "label":         data.get("label", node)[:40],
            "entity_type":   etype,
            "color":         color_map.get(etype, "#95A5A6"),
            "size":          max(8, min(40, data.get("fir_count", 0) * 4 + 8)),
            "cross_verified":data.get("cross_verified", False),
            "fusion_badge":  data.get("fusion_badge", ""),
            "roles":         data.get("roles", ""),
            "sources":       data.get("sources", ""),
            "source_count":  data.get("source_count", 1),
            "fir_count":     data.get("fir_count", 0),
            "community":     data.get("community", 0),
            "first_seen":    data.get("first_seen", ""),
            "last_seen":     data.get("last_seen", ""),
        })

    for u, v, data in G.edges(data=True):
        edges.append({
            "source":   u,
            "target":   v,
            "rel_type": data.get("rel_type", ""),
            "weight":   round(data.get("weight", 1.0), 2),
            "source_file": data.get("source", ""),
            "date":     data.get("date", ""),
            "sources":  data.get("sources", data.get("source", "")),
            "rel_types": data.get("rel_types", [data.get("rel_type", "")]),
            "events":   data.get("events", []),
        })

    graph_json = {"nodes": nodes, "edges": edges,
                  "related_firs": G.graph.get("related_firs", []),
                  "meta": {"node_count": len(nodes), "edge_count": len(edges)}}

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(graph_json, f, indent=2)

    print(f"  Exported graph JSON: {len(nodes)} nodes, {len(edges)} edges → {out_path}")
    return graph_json


def export_gexf(G: nx.Graph, out_path: str):
    export_graph = G.copy()
    export_graph.graph.pop("related_firs", None)
    for _, _, data in export_graph.edges(data=True):
        for attribute in ("events", "rel_types"):
            if attribute in data:
                data[attribute] = json.dumps(data[attribute], ensure_ascii=False)
    nx.write_gexf(export_graph, out_path)
    print(f"  Exported GEXF (Gephi) → {out_path}")


def export_relationships_csv(G: nx.Graph, out_path: str):
    records = []
    for u, v, data in G.edges(data=True):
        u_data = G.nodes[u]
        v_data = G.nodes[v]
        records.append({
            "Entity_A_ID":    u,
            "Entity_A_Label": u_data.get("label", u),
            "Entity_A_Type":  u_data.get("entity_type", "?"),
            "Entity_B_ID":    v,
            "Entity_B_Label": v_data.get("label", v),
            "Entity_B_Type":  v_data.get("entity_type", "?"),
            "Relationship":   data.get("rel_type", ""),
            "Weight":         round(data.get("weight", 1.0), 2),
            "Source":         data.get("source", ""),
            "Date":           data.get("date", ""),
            "Sources":        data.get("sources", data.get("source", "")),
            "Relationship_Types": json.dumps(
                data.get("rel_types", [data.get("rel_type", "")]), ensure_ascii=False
            ),
            "Events":          json.dumps(data.get("events", []), ensure_ascii=False),
        })
    df = pd.DataFrame(records)
    df.to_csv(out_path, index=False)
    print(f"  Exported relationships CSV: {len(df)} edges → {out_path}")
    return df


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from pipeline.graph.builder import build_graph

    G = build_graph(
        "data/processed/entities.csv",
        "data/raw/fir_500.csv",
        "data/raw/cdr_logs.csv",
        "data/raw/financial_txns.csv",
    )
    export_json(G, str(GRAPH_JSON))
    export_gexf(G, str(GRAPH_GEXF))
    export_relationships_csv(G, str(RELATIONSHIPS_CSV))
