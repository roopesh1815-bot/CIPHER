"""
CrimeNet AI — Risk Scorer
Combines four independent signals into one composite Risk_Score (0-100)
per entity:
  1. Centrality  (Influence_Score from centrality.py)     — how connected/central
  2. Anomalies   (severity-weighted count from anomaly.py) — how unusual
  3. Community   (gang size + suspect presence from community.py) — organized-crime context
  4. Hidden links (appearance count from link_predictor.py) — undisclosed connections

Follows the same fresh-build-every-run pattern as the rest of pipeline/graph.
"""

import pandas as pd
import networkx as nx
import json

SEVERITY_WEIGHT = {"High": 3, "Medium": 2, "Low": 1}

# Composite weights — must sum to 1.0
W_CENTRALITY = 0.35
W_ANOMALY    = 0.30
W_COMMUNITY  = 0.20
W_HIDDEN     = 0.15


def _normalize(series: pd.Series) -> pd.Series:
    mn, mx = series.min(), series.max()
    return (series - mn) / (mx - mn + 1e-9)


def _anomaly_component(cent_df: pd.DataFrame, anom_df: pd.DataFrame) -> pd.Series:
    """Per-entity sum of severity weights across all anomaly rows, normalized 0-1."""
    if anom_df.empty:
        return pd.Series(0.0, index=cent_df.index)

    anom_df = anom_df.copy()
    anom_df["_w"] = anom_df["Severity"].map(SEVERITY_WEIGHT).fillna(0)
    per_entity = anom_df.groupby("Canonical_ID")["_w"].sum()

    # .map() with a Series acts as a lookup and preserves cent_df's own
    # positional index automatically — no manual reindex needed.
    aligned = cent_df["Canonical_ID"].map(per_entity).fillna(0)
    return _normalize(aligned)


def _community_component(cent_df: pd.DataFrame, partition: dict, comm_df: pd.DataFrame) -> pd.Series:
    """
    Per-community risk = normalized size * cross_verified_ratio, boosted if
    the community contains a suspect, then broadcast to every member node.
    """
    comm_df = comm_df.copy()
    comm_df["_cv_ratio"] = comm_df["Cross_Verified"] / comm_df["Size"].clip(lower=1)
    comm_df["_size_norm"] = _normalize(comm_df["Size"])
    comm_df["_comm_risk"] = comm_df["_size_norm"] * comm_df["_cv_ratio"].fillna(0)
    comm_df.loc[comm_df["Has_Suspect"], "_comm_risk"] *= 1.5
    comm_df["_comm_risk"] = _normalize(comm_df["_comm_risk"])

    risk_by_cid = dict(zip(comm_df["Community_ID"], comm_df["_comm_risk"]))
    # Keeps cent_df's own index throughout — no reassignment.
    scores = cent_df["Canonical_ID"].map(partition).map(risk_by_cid).fillna(0)
    return scores


def _hidden_link_component(cent_df: pd.DataFrame, hidden_df: pd.DataFrame) -> pd.Series:
    """How many times each entity appears (as node_a or node_b) in predicted hidden links."""
    if hidden_df is None or hidden_df.empty:
        return pd.Series(0.0, index=cent_df.index)

    counts = pd.concat([hidden_df["node_a"], hidden_df["node_b"]]).value_counts()
    aligned = cent_df["Canonical_ID"].map(counts).fillna(0)
    return _normalize(aligned)


def score(cent_df: pd.DataFrame, anom_df: pd.DataFrame,
          partition: dict, comm_df: pd.DataFrame,
          hidden_df: pd.DataFrame = None) -> pd.DataFrame:

    df = cent_df.copy()

    centrality_norm = _normalize(df["Influence_Score"])
    anomaly_norm    = _anomaly_component(df, anom_df)
    community_norm  = _community_component(df, partition, comm_df)
    hidden_norm     = _hidden_link_component(df, hidden_df)

    df["Risk_Score"] = (
        centrality_norm * W_CENTRALITY +
        anomaly_norm    * W_ANOMALY +
        community_norm  * W_COMMUNITY +
        hidden_norm     * W_HIDDEN
    ) * 100
    df["Risk_Score"] = df["Risk_Score"].round(2)

    # Quantile-based tiers — adapts to this dataset's actual score distribution
    # rather than fixed cutoffs, matching the quantile approach already used
    # in anomaly.py (e.g. Fin_Count > quantile(0.95)).
    q75, q90, q97 = df["Risk_Score"].quantile([0.75, 0.90, 0.97])

    def tier(s):
        if s >= q97: return "Critical"
        if s >= q90: return "High"
        if s >= q75: return "Medium"
        return "Low"

    df["Risk_Tier"] = df["Risk_Score"].apply(tier)
    df = df.sort_values("Risk_Score", ascending=False).reset_index(drop=True)
    df["Risk_Rank"] = df.index + 1

    keep_cols = [
        "Risk_Rank", "Canonical_ID", "Label", "Entity_Type", "Roles",
        "Risk_Score", "Risk_Tier", "Influence_Score",
        "Cross_Verified", "Fusion_Badge", "Sources",
    ]
    return df[keep_cols]


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from pipeline.graph.builder             import build_graph
    from pipeline.graph.centrality          import compute as compute_centrality
    from pipeline.graph.anomaly             import detect as detect_anomalies
    from pipeline.graph.community           import detect as detect_communities
    from pipeline.intelligence.link_predictor import predict_links

    G = build_graph(
        "data/processed/entities.csv",
        "data/raw/fir_500.csv",
        "data/raw/cdr_logs.csv",
        "data/raw/financial_txns.csv",
    )

    cent_df = compute_centrality(G)
    anom_df = detect_anomalies(G, cent_df)
    partition, comm_df = detect_communities(G)
    hidden_df = predict_links(G, top_n=100)

    risk_df = score(cent_df, anom_df, partition, comm_df, hidden_df)
    risk_df.to_csv("data/processed/risk_scores.csv", index=False)

    with open("data/processed/risk_scores.json", "w") as f:
        json.dump(risk_df.to_dict(orient="records"), f, indent=2)

    print(f"\n  Risk scores computed for {len(risk_df)} entities")
    print(f"\n  Top 15 Highest-Risk Entities:")
    print(f"  {'Rank':<5} {'Name':<28} {'Type':<10} {'Score':>6}  {'Tier':<9}")
    print("  " + "-"*65)
    for _, row in risk_df.head(15).iterrows():
        print(f"  {int(row['Risk_Rank']):<5} {row['Label'][:27]:<28} {row['Entity_Type']:<10} "
              f"{row['Risk_Score']:>6.2f}  {row['Risk_Tier']:<9}")

    print(f"\n  Tier distribution:")
    print(risk_df["Risk_Tier"].value_counts().to_string())

    print(f"\nSaved to data/processed/risk_scores.csv / risk_scores.json")