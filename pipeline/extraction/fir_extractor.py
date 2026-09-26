"""
CrimeNet AI — FIR Entity Extractor
Extracts entities from fir_500.csv into unified entity format
"""

import pandas as pd
import re


def extract(fir_path: str) -> pd.DataFrame:
    df = pd.read_csv(fir_path)
    records = []

    for _, row in df.iterrows():
        fir_id = row["FIR_ID"]
        date   = row["Incident_Date"]
        dist   = row.get("District", "Unknown")

        # ── People ───────────────────────────────────────────
        people = [
            ("Complainant", row.get("Complainant_Name"), row.get("Complainant_Mobile")),
            ("Victim",      row.get("Victim_Name"),      row.get("Victim_Mobile")),
            ("Suspect",     row.get("Suspect_Name"),     row.get("Suspect_Mobile")),
            ("Associate",   row.get("Associate_Name"),   row.get("Associate_Mobile")),
            ("Witness",     row.get("Witness_Name"),     row.get("Witness_Mobile")),
        ]
        for role, name, mobile in people:
            name   = str(name).strip()
            mobile = str(mobile).strip()
            if name in ("NULL", "nan", "", "Unknown"):
                name = None
            if mobile in ("NULL", "nan", ""):
                mobile = None
            if name:
                records.append({
                    "Entity_ID":    f"ENT-{len(records)+1:06d}",
                    "Entity_Type":  "Person",
                    "Entity_Value": name,
                    "Role":         role,
                    "Mobile":       mobile or "NULL",
                    "Source_File":  "FIR",
                    "Source_ID":    fir_id,
                    "Date":         date,
                    "District":     dist,
                })
            if mobile and not name:
                records.append({
                    "Entity_ID":    f"ENT-{len(records)+1:06d}",
                    "Entity_Type":  "Mobile",
                    "Entity_Value": mobile,
                    "Role":         role,
                    "Mobile":       mobile,
                    "Source_File":  "FIR",
                    "Source_ID":    fir_id,
                    "Date":         date,
                    "District":     dist,
                })

        # ── Vehicle ──────────────────────────────────────────
        vn = str(row.get("Vehicle_Number", "NULL")).strip()
        vt = str(row.get("Vehicle_Type",   "None")).strip()
        if vn not in ("NULL", "nan", "None", ""):
            records.append({
                "Entity_ID":    f"ENT-{len(records)+1:06d}",
                "Entity_Type":  "Vehicle",
                "Entity_Value": vn,
                "Role":         vt,
                "Mobile":       "NULL",
                "Source_File":  "FIR",
                "Source_ID":    fir_id,
                "Date":         date,
                "District":     dist,
            })

        # ── Account ──────────────────────────────────────────
        acc = str(row.get("Account_Number", "NULL")).strip()
        if acc not in ("NULL", "nan", ""):
            records.append({
                "Entity_ID":    f"ENT-{len(records)+1:06d}",
                "Entity_Type":  "Account",
                "Entity_Value": acc,
                "Role":         "Financial",
                "Mobile":       "NULL",
                "Source_File":  "FIR",
                "Source_ID":    fir_id,
                "Date":         date,
                "District":     dist,
            })

        # ── Location ─────────────────────────────────────────
        loc = str(row.get("Incident_Location", "NULL")).strip()
        if loc not in ("NULL", "nan", ""):
            records.append({
                "Entity_ID":    f"ENT-{len(records)+1:06d}",
                "Entity_Type":  "Location",
                "Entity_Value": loc,
                "Role":         "Incident",
                "Mobile":       "NULL",
                "Source_File":  "FIR",
                "Source_ID":    fir_id,
                "Date":         date,
                "District":     dist,
            })

        # ── Mobiles from description (regex) ─────────────────
        desc = str(row.get("FIR_Description", ""))
        found = re.findall(r"\b9\d{9}\b", desc)
        for m in set(found):
            records.append({
                "Entity_ID":    f"ENT-{len(records)+1:06d}",
                "Entity_Type":  "Mobile",
                "Entity_Value": m,
                "Role":         "Mentioned",
                "Mobile":       m,
                "Source_File":  "FIR",
                "Source_ID":    fir_id,
                "Date":         date,
                "District":     dist,
            })

    result = pd.DataFrame(records)
    # Re-index Entity_IDs cleanly
    result["Entity_ID"] = [f"ENT-{i+1:06d}" for i in range(len(result))]
    return result


if __name__ == "__main__":
    df = extract("data/raw/fir_500.csv")
    print(f"FIR Extractor: {len(df)} entities extracted")
    print(df["Entity_Type"].value_counts().to_string())
