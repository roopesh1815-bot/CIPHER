"""
CrimeNet AI — Community / Gang Detector
Uses NetworkX Greedy Modularity (no extra packages needed)
"""

import pandas as pd
import networkx as nx
import json
from collections import defaultdict, Counter


def detect(G: nx.Graph) -> tuple:
    print("  Detecting communities...")

    from networkx.algorithms.community import greedy_modularity_communities
    communities_raw = list(greedy_modularity_communities(G, weight="weight"))
    method = "Greedy Modularity"

    partition = {}
    for cid, members in enumerate(communities_raw):
        for node in members:
            partition[node] = cid

    num_communities = len(communities_raw)
    print(f"  Method: {method} → {num_communities} communities found")

    nx.set_node_attributes(G, partition, "community")

    records = []
    for cid, members in enumerate(communities_raw):
        members = list(members)
        subgraph     = G.subgraph(members)
        entity_types = [G.nodes[n].get("entity_type", "?") for n in members]
        labels       = [G.nodes[n].get("label", "?")       for n in members]
        has_suspect  = any("Suspect" in str(G.nodes[n].get("roles", "")) for n in members)
        cross_count  = sum(1 for n in members if G.nodes[n].get("cross_verified", False))
        type_counts  = Counter(entity_types)
        dominant     = type_counts.most_common(1)[0][0]

        records.append({
            "Community_ID":    cid,
            "Size":            len(members),
            "Internal_Edges":  subgraph.number_of_edges(),
            "Dominant_Type":   dominant,
            "Has_Suspect":     has_suspect,
            "Cross_Verified":  cross_count,
            "Members":         "|".join(labels[:20]),
            "Member_IDs":      "|".join(members),
        })

    df = pd.DataFrame(records).sort_values("Size", ascending=False).reset_index(drop=True)
    df["Community_Label"] = [f"Gang-{i+1:02d}" for i in range(len(df))]

    print(f"\n  Top 10 Communities:")
    print(f"  {'Label':<12} {'Size':>5}  {'Edges':>6}  {'Suspects':>8}  {'CrossVerif':>10}")
    print("  " + "-"*50)
    for _, row in df.head(10).iterrows():
        print(f"  {row['Community_Label']:<12} {row['Size']:>5}  "
              f"{row['Internal_Edges']:>6}  {str(row['Has_Suspect']):>8}  "
              f"{row['Cross_Verified']:>10}")

    return partition, df


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
    partition, df = detect(G)
    df.to_csv("data/processed/communities.csv", index=False)

    with open("data/processed/communities.json", "w") as f:
        json.dump({
            "partition": partition,
            "summary": df.to_dict(orient="records")
        }, f, indent=2)

    print(f"\nSaved communities.csv + communities.json")
