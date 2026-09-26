"""
CrimeNet AI — Temporal Pattern Engine
Builds a timeline per entity and flags time-based patterns: activity spikes,
repeat-offence rhythms, and rule-based alerts (e.g. a mobile appearing in
3+ cases within a short window). All rule-based and explainable — no ML.
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

ALERT_WINDOW_DAYS = 90       # "short window" for the multi-case alert rule
ALERT_MIN_CASES = 3          # cases within that window to trigger an alert


def _parse_date(value):
    if pd.isna(value):
        return None
    try:
        return pd.to_datetime(value, dayfirst=True, errors="coerce")
    except Exception:
        return None


def build_entity_timeline(fir_df: pd.DataFrame) -> dict:
    """
    For every mobile number that appears as Suspect_Mobile, Associate_Mobile,
    Complainant_Mobile or Witness_Mobile, build a chronological list of the
    cases it appears in, with role and date.
    """
    print("  Building entity timelines...")

    mobile_role_cols = {
        "Suspect_Mobile": "Suspect",
        "Associate_Mobile": "Associate",
        "Complainant_Mobile": "Complainant",
        "Witness_Mobile": "Witness",
    }

    events_by_entity: dict[str, list] = {}

    for _, row in fir_df.iterrows():
        fir_date = _parse_date(row.get("FIR_Date"))
        for col, role in mobile_role_cols.items():
            mobile = row.get(col)
            if pd.isna(mobile) or not str(mobile).strip():
                continue
            mobile = str(mobile).strip()
            if mobile.lower() in {"unknown", "n/a", "na", "none", "-"}:
                continue

            events_by_entity.setdefault(mobile, []).append({
                "FIR_ID": row["FIR_ID"],
                "Role": role,
                "Date": fir_date.isoformat() if fir_date is not None and not pd.isna(fir_date) else None,
                "District": row.get("District"),
                "Crime_Type": row.get("Crime_Type"),
            })

    # sort each entity's events chronologically (undated events go last)
    for mobile, events in events_by_entity.items():
        events.sort(key=lambda e: (e["Date"] is None, e["Date"] or ""))

    print(f"  Built timelines for {len(events_by_entity)} entities (mobiles).")
    return events_by_entity


def detect_temporal_alerts(events_by_entity: dict) -> pd.DataFrame:
    """
    Rule-based alert: an entity appearing in ALERT_MIN_CASES or more distinct
    cases within any ALERT_WINDOW_DAYS-day window. Flags a burst of activity
    worth investigator attention.
    """
    print("  Scanning for temporal alerts (activity bursts)...")

    alerts = []
    for mobile, events in events_by_entity.items():
        dated = [e for e in events if e["Date"]]
        if len(dated) < ALERT_MIN_CASES:
            continue

        dates = [datetime.fromisoformat(e["Date"]) for e in dated]

        for i in range(len(dates)):
            window_end = dates[i] + pd.Timedelta(days=ALERT_WINDOW_DAYS)
            window_events = [
                dated[j] for j in range(len(dates))
                if dates[i] <= dates[j] <= window_end
            ]
            if len(window_events) >= ALERT_MIN_CASES:
                fir_ids = sorted({e["FIR_ID"] for e in window_events})
                alerts.append({
                    "Entity": mobile,
                    "Alert_Type": "Activity burst",
                    "Case_Count_In_Window": len(fir_ids),
                    "Window_Days": ALERT_WINDOW_DAYS,
                    "FIR_IDs": "|".join(fir_ids),
                    "Note": f"AI-flagged: appears in {len(fir_ids)} cases within {ALERT_WINDOW_DAYS} days — flagged for review",
                })
                break  # one alert per entity is enough; avoid duplicate overlapping windows

    df = pd.DataFrame(alerts)
    if not df.empty:
        df = df.sort_values("Case_Count_In_Window", ascending=False).reset_index(drop=True)

    print(f"  {len(df)} temporal alert(s) found.")
    return df


def build_case_type_trend(fir_df: pd.DataFrame) -> pd.DataFrame:
    """Monthly count per Crime_Type — for an Overview/trend chart."""
    print("  Building crime-type monthly trend...")

    df = fir_df.copy()
    df["FIR_Date_Parsed"] = df["FIR_Date"].apply(_parse_date)
    df = df.dropna(subset=["FIR_Date_Parsed"])
    df["Month"] = df["FIR_Date_Parsed"].dt.to_period("M").astype(str)

    trend = (
        df.groupby(["Month", "Crime_Type"])
        .size()
        .reset_index(name="Count")
        .sort_values(["Month", "Crime_Type"])
    )
    return trend


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")

    mobile_cols = ["Suspect_Mobile", "Associate_Mobile", "Complainant_Mobile", "Witness_Mobile"]
    fir_df = pd.read_csv("data/raw/fir_500.csv", dtype={col: str for col in mobile_cols})
    
    events_by_entity = build_entity_timeline(fir_df)
    alerts_df = detect_temporal_alerts(events_by_entity)
    trend_df = build_case_type_trend(fir_df)

    Path("data/processed").mkdir(parents=True, exist_ok=True)

    with open("data/processed/entity_timelines.json", "w") as f:
        json.dump(events_by_entity, f, indent=2)

    alerts_df.to_csv("data/processed/temporal_alerts.csv", index=False)
    trend_df.to_csv("data/processed/crime_type_trend.csv", index=False)

    print("\nSaved entity_timelines.json + temporal_alerts.csv + crime_type_trend.csv")

    if not alerts_df.empty:
        print("\nTop temporal alerts:")
        print(alerts_df.head(10).to_string(index=False))
    else:
        print("\nNo activity-burst alerts triggered at current thresholds.")