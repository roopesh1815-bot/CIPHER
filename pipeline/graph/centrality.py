"""
CrimeNet AI — Centrality Analyser
Computes Degree, Betweenness, PageRank centrality
Identifies key influencers in the criminal network
"""

import pandas as pd
import networkx as nx


def compute(G: nx.Graph) -> pd.DataFrame:
    print("  Computing centrality scores...")

    # ── Degree centrality ─────────────────────────────────────
    degree_raw  = dict(G.degree(weight="weight"))
    degree_norm = nx.degree_centrality(G)

    # ── Betweenness (key bridges/brokers) ─────────────────────
    print("  → Betweenness (may take a moment)...")
    between = nx.betweenness_centrality(G, weight="weight", normalized=True, k=min(100, len(G)))

    # ── PageRank (influence propagation) ──────────────────────
    print("  → PageRank...")
    pagerank = nx.pagerank(G, weight="weight", alpha=0.85, max_iter=200)

    # ── Closeness ─────────────────────────────────────────────
    print("  → Closeness...")
    closeness = nx.closeness_centrality(G)

    # ── Assemble results ──────────────────────────────────────
    records = []
    for node in G.nodes():
        data = G.nodes[node]
        records.append({
            "Canonical_ID":    node,
            "Label":           data.get("label", node),
            "Entity_Type":     data.get("entity_type", "Unknown"),
            "Roles":           data.get("roles", ""),
            "Degree_Raw":      degree_raw.get(node, 0),
            "Degree_Norm":     round(degree_norm.get(node, 0), 4),
            "Betweenness":     round(between.get(node, 0), 4),
            "PageRank":        round(pagerank.get(node, 0), 6),
            "Closeness":       round(closeness.get(node, 0), 4),
            "Cross_Verified":  data.get("cross_verified", False),
            "Fusion_Badge":    data.get("fusion_badge", ""),
            "FIR_Count":       data.get("fir_count", 0),
            "CDR_Count":       data.get("cdr_count", 0),
            "Fin_Count":       data.get("fin_count", 0),
            "Soc_Count":       data.get("soc_count", 0),
            "Sources":         data.get("sources", ""),
        })

    df = pd.DataFrame(records)

    # ── Composite influence score (0–100) ─────────────────────
    def norm(series):
        mn, mx = series.min(), series.max()
        return (series - mn) / (mx - mn + 1e-9)

    df["Influence_Score"] = (
        norm(df["Degree_Norm"])  * 30 +
        norm(df["Betweenness"])  * 35 +
        norm(df["PageRank"])     * 25 +
        norm(df["Closeness"])    * 10
    ).round(2)

    df = df.sort_values("Influence_Score", ascending=False).reset_index(drop=True)
    df["Rank"] = df.index + 1

    print(f"  Centrality computed for {len(df)} nodes")
    print(f"\n  Top 10 Influencers:")
    print(f"  {'Rank':<5} {'Name':<28} {'Type':<12} {'Score':>6}  {'Between':>8}  {'PageRank':>9}")
    print("  " + "-"*72)
    for _, row in df.head(10).iterrows():
        print(f"  {int(row['Rank']):<5} {row['Label'][:27]:<28} {row['Entity_Type']:<12} "
              f"{row['Influence_Score']:>6.1f}  {row['Betweenness']:>8.4f}  {row['PageRank']:>9.6f}")

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
    df = compute(G)
    df.to_csv("data/processed/centrality.csv", index=False)
    print(f"\nSaved to data/processed/centrality.csv")
