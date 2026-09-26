"""
CrimeNet AI / CIPHER — Master Pipeline
Single entry point for the full Phase 1 intelligence pipeline. Builds the
graph once and threads it through every stage, instead of each script
rebuilding it independently. Run this instead of the individual modules
for anything beyond isolated testing.

Usage:
    python -m pipeline.run_pipeline
"""

import sys
import time
import json
sys.path.insert(0, ".")

from pipeline.graph.builder               import build_graph
from pipeline.graph.centrality            import compute as compute_centrality
from pipeline.graph.anomaly               import detect as detect_anomalies
from pipeline.graph.community             import detect as detect_communities
from pipeline.intelligence.link_predictor import predict_links
from pipeline.intelligence.risk_scorer    import score as compute_risk
from pipeline.intelligence.case_summariser import summarise_all

try:
    from core.audit import log_action
    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False

ENTITIES_PATH = "data/processed/entities.csv"
FIR_PATH      = "data/raw/fir_500.csv"
CDR_PATH      = "data/raw/cdr_logs.csv"
FIN_PATH      = "data/raw/financial_txns.csv"

OUT_DIR = "data/processed"


def _stage(label: str):
    """Small helper so every stage prints a consistent timed header."""
    print(f"\n{'='*70}\n  {label}\n{'='*70}")
    return time.time()


def _elapsed(t0: float) -> str:
    return f"{time.time() - t0:.2f}s"


def run() -> dict:
    """
    Runs the full pipeline end to end. Returns a dict of every intermediate
    result (G, cent_df, anom_df, partition, comm_df, hidden_df, risk_df,
    summary_df) in case a caller (e.g. a future FastAPI/Streamlit layer)
    wants the in-memory objects instead of re-reading the CSVs it saves.
    """
    pipeline_start = time.time()
    run_id = f"RUN-{int(pipeline_start)}"

    if AUDIT_AVAILABLE:
        log_action("SYSTEM", "PIPELINE_RUN_START", target=run_id)

    print(f"\n{'#'*70}")
    print(f"#  CIPHER — Full Intelligence Pipeline")
    print(f"#  Run ID: {run_id}")
    print(f"{'#'*70}")

    # ── Stage 1: Graph construction ───────────────────────────
    t0 = _stage("Stage 1/6 — Building graph")
    G = build_graph(ENTITIES_PATH, FIR_PATH, CDR_PATH, FIN_PATH)
    print(f"  Done in {_elapsed(t0)}")

    # ── Stage 2: Centrality ────────────────────────────────────
    t0 = _stage("Stage 2/6 — Centrality analysis")
    cent_df = compute_centrality(G)
    cent_df.to_csv(f"{OUT_DIR}/centrality.csv", index=False)
    print(f"  Done in {_elapsed(t0)} — saved centrality.csv")

    # ── Stage 3: Anomaly detection ─────────────────────────────
    t0 = _stage("Stage 3/6 — Anomaly detection")
    anom_df = detect_anomalies(G, cent_df)
    anom_df.to_csv(f"{OUT_DIR}/anomalies.csv", index=False)
    print(f"  Done in {_elapsed(t0)} — saved anomalies.csv")

    # ── Stage 4: Community / gang detection ─────────────────────
    t0 = _stage("Stage 4/6 — Community detection")
    partition, comm_df = detect_communities(G)
    comm_df.to_csv(f"{OUT_DIR}/communities.csv", index=False)
    with open(f"{OUT_DIR}/communities.json", "w") as f:
        json.dump({"partition": partition, "summary": comm_df.to_dict(orient="records")}, f, indent=2)
    print(f"  Done in {_elapsed(t0)} — saved communities.csv/.json")

    # ── Stage 5: Hidden link prediction + risk scoring ──────────
    t0 = _stage("Stage 5/6 — Link prediction & risk scoring")
    hidden_df = predict_links(G, top_n=100)
    hidden_df.to_csv(f"{OUT_DIR}/hidden_links.csv", index=False)
    hidden_df.to_json(f"{OUT_DIR}/hidden_links.json", orient="records", indent=2)

    risk_df = compute_risk(cent_df, anom_df, partition, comm_df, hidden_df)
    risk_df.to_csv(f"{OUT_DIR}/risk_scores.csv", index=False)
    with open(f"{OUT_DIR}/risk_scores.json", "w") as f:
        json.dump(risk_df.to_dict(orient="records"), f, indent=2)
    print(f"  Done in {_elapsed(t0)} — saved hidden_links + risk_scores")

    # ── Stage 6: Case summaries ──────────────────────────────────
    t0 = _stage("Stage 6/6 — Case summarisation")
    summary_df = summarise_all(FIR_PATH, ENTITIES_PATH, risk_df, partition, comm_df, anom_df)
    summary_df.to_csv(f"{OUT_DIR}/case_summaries.csv", index=False)
    with open(f"{OUT_DIR}/case_summaries.json", "w") as f:
        json.dump(summary_df.to_dict(orient="records"), f, indent=2)
    print(f"  Done in {_elapsed(t0)} — saved case_summaries.csv/.json")

    total_time = time.time() - pipeline_start
    tier_counts = risk_df["Risk_Tier"].value_counts().to_dict()

    print(f"\n{'#'*70}")
    print(f"#  PIPELINE COMPLETE — {total_time:.2f}s total")
    print(f"#  Nodes: {G.number_of_nodes()}  |  Edges: {G.number_of_edges()}")
    print(f"#  Communities: {len(comm_df)}  |  Anomalies: {len(anom_df)}")
    print(f"#  Risk tiers: {tier_counts}")
    print(f"#  Cases summarised: {len(summary_df)}")
    print(f"{'#'*70}\n")

    if AUDIT_AVAILABLE:
        log_action(
            "SYSTEM", "PIPELINE_RUN_COMPLETE", target=run_id,
            details=(f"duration={total_time:.2f}s nodes={G.number_of_nodes()} "
                      f"edges={G.number_of_edges()} anomalies={len(anom_df)} "
                      f"critical_risk={tier_counts.get('Critical', 0)}")
        )

    return {
        "G": G, "cent_df": cent_df, "anom_df": anom_df,
        "partition": partition, "comm_df": comm_df,
        "hidden_df": hidden_df, "risk_df": risk_df,
        "summary_df": summary_df, "run_id": run_id,
        "duration_seconds": total_time,
    }


if __name__ == "__main__":
    run()