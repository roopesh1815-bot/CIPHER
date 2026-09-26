"""
CIPHER — Hidden Link Prediction
Predicts likely-but-unobserved relationships between entities using
Jaccard Coefficient and Adamic-Adar Index over the existing graph's
common-neighbor structure. Surfaces pairs of people/accounts/vehicles
that are probably connected but have no direct edge yet — e.g. two
suspects who both call the same third party but never call each other.

Follows the same load pattern as pipeline/graph/builder.py: rebuilds
the graph fresh from the same 4 CSVs each run, no saved graph file.
"""

import json
import logging
import networkx as nx
import pandas as pd

from pipeline.graph.builder import build_graph
from core.config import (
    CDR_CSV,
    ENTITIES_CSV,
    FINANCIAL_CSV,
    FIR_CSV,
    LINK_PREDICTIONS_CSV,
    LINK_PREDICTIONS_JSON,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ENTITIES_PATH = ENTITIES_CSV
FIR_PATH = FIR_CSV
CDR_PATH = CDR_CSV
FIN_PATH = FINANCIAL_CSV
OUT_CSV = LINK_PREDICTIONS_CSV
OUT_JSON = LINK_PREDICTIONS_JSON

MIN_COMMON_NEIGHBORS = 1   # candidate pairs must share at least this many neighbors
TOP_N = 100                 # how many predicted links to keep, ranked by combined score


def _candidate_pairs(G: nx.Graph):
    """
    Yields non-adjacent node pairs that share at least MIN_COMMON_NEIGHBORS
    common neighbors. Scanning all non-edges in a graph this size (thousands
    of nodes) is O(n^2) and wasteful — almost all of it would be zero-scoring
    pairs with no shared neighbors anyway. Restricting to 2-hop neighborhoods
    keeps this fast and every candidate meaningful.
    """
    seen = set()
    for node in G.nodes():
        neighbors = set(G.neighbors(node))
        two_hop = set()
        for n in neighbors:
            two_hop.update(G.neighbors(n))
        two_hop.discard(node)
        two_hop -= neighbors  # exclude already-direct neighbors

        for other in two_hop:
            pair = tuple(sorted((node, other)))
            if pair in seen:
                continue
            seen.add(pair)
            common = neighbors & set(G.neighbors(other))
            if len(common) >= MIN_COMMON_NEIGHBORS:
                yield pair


def predict_links(G: nx.Graph, top_n: int = TOP_N) -> pd.DataFrame:
    """
    Runs Jaccard + Adamic-Adar over candidate pairs and returns a ranked
    DataFrame of predicted hidden links.
    """
    pairs = list(_candidate_pairs(G))
    logger.info(f"Evaluating {len(pairs)} candidate pairs for hidden links...")

    if not pairs:
        return pd.DataFrame(columns=[
            "node_a", "node_b", "label_a", "label_b",
            "entity_type_a", "entity_type_b",
            "jaccard", "adamic_adar", "common_neighbors", "shared_neighbors",
            "combined_score",
        ])

    jaccard_scores = {(u, v): s for u, v, s in nx.jaccard_coefficient(G, pairs)}
    aa_scores      = {(u, v): s for u, v, s in nx.adamic_adar_index(G, pairs)}

    rows = []
    for (u, v) in pairs:
        j  = jaccard_scores.get((u, v), 0.0)
        aa = aa_scores.get((u, v), 0.0)
        common = list(nx.common_neighbors(G, u, v))

        # Combined score: Adamic-Adar rewards rare shared connectors more
        # heavily than Jaccard alone (a shared low-degree "fixer" node is a
        # stronger signal than a shared high-degree hub like a common city).
        combined = (0.4 * j) + (0.6 * (aa / (1 + aa)))  # aa normalised into 0-1 range

        rows.append({
            "node_a": u,
            "node_b": v,
            "label_a": G.nodes[u].get("label", "?"),
            "label_b": G.nodes[v].get("label", "?"),
            "entity_type_a": G.nodes[u].get("entity_type", "?"),
            "entity_type_b": G.nodes[v].get("entity_type", "?"),
            "jaccard": round(j, 4),
            "adamic_adar": round(aa, 4),
            "common_neighbors": len(common),
            "shared_neighbors": "|".join(
                str(G.nodes[n].get("label", n)) for n in common
            ),
            "combined_score": round(combined, 4),
        })

    df = pd.DataFrame(rows).sort_values("combined_score", ascending=False).head(top_n)
    df.reset_index(drop=True, inplace=True)
    return df


def save_predictions(df: pd.DataFrame) -> None:
    df.to_csv(OUT_CSV, index=False)
    df.to_json(OUT_JSON, orient="records", indent=2)
    logger.info(f"Saved {len(df)} predicted hidden links to {OUT_CSV} / {OUT_JSON}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")

    G = build_graph(str(ENTITIES_PATH), str(FIR_PATH), str(CDR_PATH), str(FIN_PATH))

    df = predict_links(G, top_n=TOP_N)
    save_predictions(df)

    print(f"\nTop 10 predicted hidden links:")
    for _, row in df.head(10).iterrows():
        print(f"  {row['label_a']:<25} <-> {row['label_b']:<25} "
              f"score={row['combined_score']:.3f}  common_neighbors={row['common_neighbors']}")