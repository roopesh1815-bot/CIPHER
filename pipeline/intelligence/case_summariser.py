"""
CrimeNet AI — Case Summariser
Builds a human-readable investigative brief per FIR case: who's involved,
their risk scores, gang/community membership, and any anomaly flags.
Template-based (no LLM call) — deterministic, works offline, and every
summary is traceable back to the exact data that produced it.
"""

import pandas as pd
import json


def _entity_row(canonical_id: str, risk_df: pd.DataFrame) -> dict:
    match = risk_df[risk_df["Canonical_ID"] == canonical_id]
    if match.empty:
        return {"Label": canonical_id, "Risk_Score": 0.0, "Risk_Tier": "Unknown", "Roles": ""}
    return match.iloc[0].to_dict()


def _describe_entity(row: dict) -> str:
    tier_phrase = {
        "Critical": "flagged as CRITICAL risk",
        "High": "flagged as high risk",
        "Medium": "showing moderate risk indicators",
        "Low": "showing low risk indicators",
        "Unknown": "not yet risk-scored",
    }.get(row.get("Risk_Tier", "Unknown"), "not yet risk-scored")

    return f"{row.get('Label', '?')} ({row.get('Entity_Type', '?')}, {tier_phrase}, score {row.get('Risk_Score', 0):.1f})"


def summarise_case(fir_row: pd.Series, risk_df: pd.DataFrame,
                    partition: dict, comm_df: pd.DataFrame,
                    anom_df: pd.DataFrame, val_to_cid: dict) -> dict:
    """
    Builds one case brief. fir_row is a row from fir_500.csv.
    val_to_cid maps entity value/mobile -> Canonical_ID (same helper logic as builder.py).
    """
    fir_id = str(fir_row.get("FIR_ID", "?"))
    crime_type = str(fir_row.get("Crime_Type", "Unknown"))
    location = str(fir_row.get("Incident_Location", "Unknown"))
    date = str(fir_row.get("Incident_Date", "Unknown"))

    def resolve(name_col, mob_col=None):
        name = str(fir_row.get(name_col, "")).strip().title()
        if name and name not in ("Null", "Nan", "Unknown", ""):
            cid = val_to_cid.get(name)
            if cid:
                return cid
        if mob_col:
            mob = str(fir_row.get(mob_col, "")).strip()
            if mob and mob not in ("NULL", "nan", ""):
                return val_to_cid.get(mob)
        return None

    suspect_cid = resolve("Suspect_Name", "Suspect_Mobile")
    victim_cid  = resolve("Victim_Name",  "Victim_Mobile")
    assoc_cid   = resolve("Associate_Name", "Associate_Mobile")

    involved = [cid for cid in [suspect_cid, victim_cid, assoc_cid] if cid]
    entity_rows = [_entity_row(cid, risk_df) for cid in involved]

    # Highest-risk person drives the headline
    if entity_rows:
        lead = max(entity_rows, key=lambda r: r.get("Risk_Score", 0))
    else:
        lead = None

    # Gang/community context for the suspect
    gang_note = ""
    if suspect_cid and suspect_cid in partition:
        cid_num = partition[suspect_cid]
        crow = comm_df[comm_df["Community_ID"] == cid_num]
        if not crow.empty:
            crow = crow.iloc[0]
            if crow["Size"] >= 5:
                gang_note = (f"The suspect is part of {crow['Community_Label']}, "
                             f"a cluster of {int(crow['Size'])} linked entities "
                             f"({'with' if crow['Has_Suspect'] else 'without'} other known suspects).")

    # Anomalies touching anyone in this case
    case_anomalies = anom_df[anom_df["Canonical_ID"].isin(involved)] if not anom_df.empty else pd.DataFrame()
    anomaly_notes = [
        f"{row['Label']}: {row['Anomaly_Type']} ({row['Anomaly_Detail']})"
        for _, row in case_anomalies.iterrows()
    ]

    # ── Assemble narrative (template, not LLM) ────────────────
    lines = [f"FIR {fir_id} — {crime_type} at {location} on {date}."]

    if lead:
        lines.append(f"Highest-risk party in this case: {_describe_entity(lead)}.")

    if entity_rows:
        others = [_describe_entity(r) for r in entity_rows if r != lead]
        if others:
            lines.append("Other entities involved: " + "; ".join(others) + ".")

    if gang_note:
        lines.append(gang_note)

    if anomaly_notes:
        lines.append("Anomaly flags: " + " | ".join(anomaly_notes))
    else:
        lines.append("No anomaly flags on entities in this case.")

    narrative = " ".join(lines)

    return {
        "FIR_ID": fir_id,
        "Crime_Type": crime_type,
        "Location": location,
        "Date": date,
        "Suspect_ID": suspect_cid,
        "Victim_ID": victim_cid,
        "Lead_Risk_Score": lead.get("Risk_Score", 0) if lead else 0,
        "Lead_Risk_Tier": lead.get("Risk_Tier", "Unknown") if lead else "Unknown",
        "Num_Anomalies": len(anomaly_notes),
        "Narrative": narrative,
    }


def summarise_all(fir_path: str, entities_path: str, risk_df: pd.DataFrame,
                   partition: dict, comm_df: pd.DataFrame, anom_df: pd.DataFrame) -> pd.DataFrame:
    fir = pd.read_csv(fir_path)
    entities = pd.read_csv(entities_path)

    val_to_cid = {}
    for _, row in entities.iterrows():
        val_to_cid[str(row["Entity_Value"]).strip().title()] = row["Canonical_ID"]
        mob = str(row.get("Mobile", "NULL")).strip()
        if mob not in ("NULL", "nan", ""):
            val_to_cid[mob] = row["Canonical_ID"]

    summaries = [
        summarise_case(row, risk_df, partition, comm_df, anom_df, val_to_cid)
        for _, row in fir.iterrows()
    ]
    df = pd.DataFrame(summaries)
    df = df.sort_values("Lead_Risk_Score", ascending=False).reset_index(drop=True)
    return df


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from pipeline.graph.builder               import build_graph
    from pipeline.graph.centrality            import compute as compute_centrality
    from pipeline.graph.anomaly               import detect as detect_anomalies
    from pipeline.graph.community             import detect as detect_communities
    from pipeline.intelligence.link_predictor import predict_links
    from pipeline.intelligence.risk_scorer    import score as compute_risk

    ENTITIES_PATH = "data/processed/entities.csv"
    FIR_PATH      = "data/raw/fir_500.csv"
    CDR_PATH      = "data/raw/cdr_logs.csv"
    FIN_PATH      = "data/raw/financial_txns.csv"

    G = build_graph(ENTITIES_PATH, FIR_PATH, CDR_PATH, FIN_PATH)

    cent_df = compute_centrality(G)
    anom_df = detect_anomalies(G, cent_df)
    partition, comm_df = detect_communities(G)
    hidden_df = predict_links(G, top_n=100)
    risk_df = compute_risk(cent_df, anom_df, partition, comm_df, hidden_df)

    summary_df = summarise_all(FIR_PATH, ENTITIES_PATH, risk_df, partition, comm_df, anom_df)
    summary_df.to_csv("data/processed/case_summaries.csv", index=False)

    with open("data/processed/case_summaries.json", "w") as f:
        json.dump(summary_df.to_dict(orient="records"), f, indent=2)

    print(f"\n  Case summaries generated: {len(summary_df)}")
    print(f"\n  Top 5 Highest-Risk Cases:\n")
    for _, row in summary_df.head(5).iterrows():
        print(f"  [{row['FIR_ID']}] Tier={row['Lead_Risk_Tier']} Score={row['Lead_Risk_Score']:.1f}")
        print(f"    {row['Narrative']}\n")

    print(f"Saved to data/processed/case_summaries.csv / case_summaries.json")