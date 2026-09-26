"""
CIPHER master pipeline.

Runs the existing extraction, graph, intelligence, and temporal stages in
order. Use this entry point to refresh the configured analytical artifacts.
"""

import json
import sys
import time

import pandas as pd

sys.path.insert(0, ".")

from core.config import (
    ANOMALIES_CSV,
    CASE_SUMMARIES_CSV,
    CASE_SUMMARIES_JSON,
    CDR_CSV,
    CENTRALITY_CSV,
    COMMUNITIES_CSV,
    COMMUNITIES_JSON,
    ENTITIES_CSV,
    FINANCIAL_CSV,
    FIR_CSV,
    GRAPH_GEXF,
    GRAPH_JSON,
    RELATIONSHIPS_CSV,
    RISK_SCORES_CSV,
    RISK_SCORES_JSON,
    SOCIAL_CSV,
)
from pipeline.extraction.cdr_extractor import extract as extract_cdr
from pipeline.extraction.entity_resolver import resolve
from pipeline.extraction.financial_extractor import extract as extract_financial
from pipeline.extraction.fir_extractor import extract as extract_fir
from pipeline.extraction.fusion_tagger import tag as tag_fusion
from pipeline.extraction.social_extractor import extract as extract_social
from pipeline.graph.anomaly import detect as detect_anomalies
from pipeline.graph.builder import build_graph
from pipeline.graph.centrality import compute as compute_centrality
from pipeline.graph.community import detect as detect_communities
from pipeline.graph.exporter import export_gexf, export_json, export_relationships_csv
from pipeline.intelligence.case_summariser import summarise_all
from pipeline.intelligence.link_predictor import predict_links, save_predictions
from pipeline.intelligence.risk_scorer import score as compute_risk
from pipeline.intelligence.temporal_engine import run as run_temporal

try:
    from core.audit import log_action
    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False


def _stage(label: str):
    print(f"\n{'=' * 70}\n  {label}\n{'=' * 70}")
    return time.time()


def _elapsed(start: float) -> str:
    return f"{time.time() - start:.2f}s"


def _write_json(path, payload) -> None:
    with open(path, "w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, indent=2, default=str)


def run() -> dict:
    """Run all existing stages and return their in-memory results."""
    pipeline_start = time.time()
    run_id = f"RUN-{int(pipeline_start)}"
    if AUDIT_AVAILABLE:
        log_action("SYSTEM", "PIPELINE_RUN_START", target=run_id)

    print(f"\n{'#' * 70}\n#  CIPHER — Full Intelligence Pipeline\n#  Run ID: {run_id}\n{'#' * 70}")

    t0 = _stage("Stage 1/11 — Raw extraction")
    extracted = pd.concat(
        [
            extract_fir(str(FIR_CSV)),
            extract_cdr(str(CDR_CSV)),
            extract_financial(str(FINANCIAL_CSV)),
            extract_social(str(SOCIAL_CSV)),
        ],
        ignore_index=True,
    )
    print(f"  Extracted {len(extracted)} source entity records in {_elapsed(t0)}")

    t0 = _stage("Stage 2/11 — Entity resolution and fusion")
    resolved = resolve(extracted)
    resolved.to_csv(ENTITIES_CSV, index=False)
    tagged = tag_fusion(str(ENTITIES_CSV))
    tagged.to_csv(ENTITIES_CSV, index=False)
    print(f"  Resolved and tagged {len(tagged)} entities in {_elapsed(t0)}")

    t0 = _stage("Stage 3/11 — Graph construction")
    G = build_graph(str(ENTITIES_CSV), str(FIR_CSV), str(CDR_CSV), str(FINANCIAL_CSV))
    print(f"  Done in {_elapsed(t0)}")

    t0 = _stage("Stage 4/11 — Centrality analysis")
    cent_df = compute_centrality(G)
    cent_df.to_csv(CENTRALITY_CSV, index=False)
    print(f"  Done in {_elapsed(t0)}")

    t0 = _stage("Stage 5/11 — Anomaly detection")
    anom_df = detect_anomalies(G, cent_df)
    anom_df.to_csv(ANOMALIES_CSV, index=False)
    print(f"  Done in {_elapsed(t0)}")

    t0 = _stage("Stage 6/11 — Community detection")
    partition, comm_df = detect_communities(G)
    comm_df.to_csv(COMMUNITIES_CSV, index=False)
    _write_json(COMMUNITIES_JSON, {
        "partition": partition,
        "summary": comm_df.to_dict(orient="records"),
    })
    print(f"  Done in {_elapsed(t0)}")

    t0 = _stage("Stage 7/11 — Graph export")
    export_json(G, str(GRAPH_JSON))
    export_gexf(G, str(GRAPH_GEXF))
    relationships_df = export_relationships_csv(G, str(RELATIONSHIPS_CSV))
    print(f"  Exported {len(relationships_df)} relationships in {_elapsed(t0)}")

    t0 = _stage("Stage 8/11 — Hidden-link prediction")
    hidden_df = predict_links(G, top_n=100)
    save_predictions(hidden_df)
    print(f"  Done in {_elapsed(t0)} — saved configured link-prediction artifacts")

    t0 = _stage("Stage 9/11 — Risk scoring")
    risk_df = compute_risk(cent_df, anom_df, partition, comm_df, hidden_df)
    risk_df.to_csv(RISK_SCORES_CSV, index=False)
    _write_json(RISK_SCORES_JSON, risk_df.to_dict(orient="records"))
    print(f"  Done in {_elapsed(t0)}")

    t0 = _stage("Stage 10/11 — Case summaries")
    summary_df = summarise_all(
        str(FIR_CSV), str(ENTITIES_CSV), risk_df, partition, comm_df, anom_df
    )
    summary_df.to_csv(CASE_SUMMARIES_CSV, index=False)
    _write_json(CASE_SUMMARIES_JSON, summary_df.to_dict(orient="records"))
    print(f"  Done in {_elapsed(t0)}")

    t0 = _stage("Stage 11/11 — Temporal analysis")
    temporal_results = run_temporal(fir_path=FIR_CSV)
    print(f"  Done in {_elapsed(t0)}")

    total_time = time.time() - pipeline_start
    tier_counts = risk_df["Risk_Tier"].value_counts().to_dict()
    print(f"\n{'#' * 70}")
    print(f"#  PIPELINE COMPLETE — {total_time:.2f}s total")
    print(f"#  Nodes: {G.number_of_nodes()}  |  Edges: {G.number_of_edges()}")
    print(f"#  Communities: {len(comm_df)}  |  Anomalies: {len(anom_df)}")
    print(f"#  Risk tiers: {tier_counts}")
    print(f"#  Cases summarised: {len(summary_df)}")
    print(f"{'#' * 70}\n")

    if AUDIT_AVAILABLE:
        log_action(
            "SYSTEM",
            "PIPELINE_RUN_COMPLETE",
            target=run_id,
            details=(
                f"duration={total_time:.2f}s nodes={G.number_of_nodes()} "
                f"edges={G.number_of_edges()} anomalies={len(anom_df)} "
                f"critical_risk={tier_counts.get('Critical', 0)}"
            ),
        )

    return {
        "G": G,
        "cent_df": cent_df,
        "anom_df": anom_df,
        "partition": partition,
        "comm_df": comm_df,
        "hidden_df": hidden_df,
        "risk_df": risk_df,
        "summary_df": summary_df,
        "temporal_results": temporal_results,
        "run_id": run_id,
        "duration_seconds": total_time,
    }


if __name__ == "__main__":
    run()
