"""
CrimeNet AI — Anomaly Detector
Flags unusual patterns in the criminal network:
- Degree spikes (sudden high connectivity)
- Bridge nodes (betweenness >> degree)
- Isolated hubs (connected to many but in few sources)
- Suspicious financial nodes
- Cross-role anomalies (same entity in suspect + victim roles)
"""

import pandas as pd
import networkx as nx


def detect(G: nx.Graph, centrality_df: pd.DataFrame) -> pd.DataFrame:
    print("  Running anomaly detection...")
    anomalies = []

    df = centrality_df.copy()

    # ── Anomaly 1: Degree Spike ───────────────────────────────
    deg_mean = df["Degree_Raw"].mean()
    deg_std  = df["Degree_Raw"].std()
    spikes   = df[df["Degree_Raw"] > deg_mean + 2.5 * deg_std]
    for _, row in spikes.iterrows():
        anomalies.append({
            "Canonical_ID":   row["Canonical_ID"],
            "Label":          row["Label"],
            "Entity_Type":    row["Entity_Type"],
            "Anomaly_Type":   "Degree Spike",
            "Anomaly_Detail": f"Degree {row['Degree_Raw']} >> mean {deg_mean:.1f}",
            "Severity":       "High" if row["Degree_Raw"] > deg_mean + 4 * deg_std else "Medium",
        })

    # ── Anomaly 2: Bridge Node (high betweenness, low degree) ─
    bt_mean = df["Betweenness"].mean()
    bt_std  = df["Betweenness"].std()
    bridges = df[
        (df["Betweenness"] > bt_mean + 2 * bt_std) &
        (df["Degree_Raw"]  < df["Degree_Raw"].quantile(0.6))
    ]
    for _, row in bridges.iterrows():
        anomalies.append({
            "Canonical_ID":   row["Canonical_ID"],
            "Label":          row["Label"],
            "Entity_Type":    row["Entity_Type"],
            "Anomaly_Type":   "Bridge Node",
            "Anomaly_Detail": f"Betweenness {row['Betweenness']:.4f} with low degree {row['Degree_Raw']}",
            "Severity":       "High",
        })

    # ── Anomaly 3: Multi-Source Suspect ───────────────────────
    multi_src = df[
        (df["Entity_Type"] == "Person") &
        (df["Sources"].str.count(r"\|") >= 2) &
        (df["Roles"].str.contains("Suspect", na=False))
    ]
    for _, row in multi_src.iterrows():
        anomalies.append({
            "Canonical_ID":   row["Canonical_ID"],
            "Label":          row["Label"],
            "Entity_Type":    row["Entity_Type"],
            "Anomaly_Type":   "Multi-Source Suspect",
            "Anomaly_Detail": f"Suspect confirmed in sources: {row['Sources']}",
            "Severity":       "High",
        })

    # ── Anomaly 4: Cross-Role Entity ─────────────────────────
    cross_role = df[
        df["Roles"].str.contains("Suspect", na=False) &
        df["Roles"].str.contains("Witness|Complainant", na=False)
    ]
    for _, row in cross_role.iterrows():
        anomalies.append({
            "Canonical_ID":   row["Canonical_ID"],
            "Label":          row["Label"],
            "Entity_Type":    row["Entity_Type"],
            "Anomaly_Type":   "Cross-Role Conflict",
            "Anomaly_Detail": f"Same entity in roles: {row['Roles']}",
            "Severity":       "Medium",
        })

    # ── Anomaly 5: High Financial Activity ───────────────────
    fin_heavy = df[
        (df["Fin_Count"] > df["Fin_Count"].quantile(0.95)) &
        (df["Fin_Count"] > 0)
    ]
    for _, row in fin_heavy.iterrows():
        anomalies.append({
            "Canonical_ID":   row["Canonical_ID"],
            "Label":          row["Label"],
            "Entity_Type":    row["Entity_Type"],
            "Anomaly_Type":   "High Financial Activity",
            "Anomaly_Detail": f"Linked to {row['Fin_Count']} financial records",
            "Severity":       "Medium",
        })

    result = pd.DataFrame(anomalies)
    if not result.empty:
        result = result.drop_duplicates(subset=["Canonical_ID","Anomaly_Type"])

    sev_order = {"High": 0, "Medium": 1, "Low": 2}
    if not result.empty:
        result["_sev"] = result["Severity"].map(sev_order)
        result = result.sort_values("_sev").drop(columns="_sev").reset_index(drop=True)

    print(f"  Anomalies detected: {len(result)}")
    if not result.empty:
        print(result["Anomaly_Type"].value_counts().to_string())

    return result


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from pipeline.graph.builder    import build_graph
    from pipeline.graph.centrality import compute

    G  = build_graph(
        "data/processed/entities.csv",
        "data/raw/fir_500.csv",
        "data/raw/cdr_logs.csv",
        "data/raw/financial_txns.csv",
    )
    cent_df = compute(G)
    anom_df = detect(G, cent_df)
    anom_df.to_csv("data/processed/anomalies.csv", index=False)
    print(f"\nSaved to data/processed/anomalies.csv")
