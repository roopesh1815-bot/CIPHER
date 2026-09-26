"""
CrimeNet AI — CDR Entity Extractor
Extracts caller/callee mobile entities and call relationships from CDR logs
"""

import pandas as pd


def extract(cdr_path: str) -> pd.DataFrame:
    df = pd.read_csv(cdr_path)
    records = []

    for _, row in df.iterrows():
        cdr_id = row["CDR_ID"]
        date   = str(row.get("Call_DateTime", ""))[:10]
        tower  = row.get("Cell_Tower", "Unknown")

        for role, col in [("Caller", "Caller_Mobile"), ("Callee", "Callee_Mobile")]:
            mob = str(row.get(col, "")).strip()
            if not mob or mob in ("nan", "NULL", ""):
                continue
            records.append({
                "Entity_ID":    "",
                "Entity_Type":  "Mobile",
                "Entity_Value": mob,
                "Role":         role,
                "Mobile":       mob,
                "Source_File":  "CDR",
                "Source_ID":    cdr_id,
                "Date":         date,
                "District":     tower,   # tower used as location proxy
            })

        # Cell tower as location entity
        if tower not in ("Unknown", "nan", ""):
            records.append({
                "Entity_ID":    "",
                "Entity_Type":  "CellTower",
                "Entity_Value": tower,
                "Role":         "Location",
                "Mobile":       "NULL",
                "Source_File":  "CDR",
                "Source_ID":    cdr_id,
                "Date":         date,
                "District":     tower,
            })

    result = pd.DataFrame(records)
    result["Entity_ID"] = [f"CDR-ENT-{i+1:06d}" for i in range(len(result))]
    return result


if __name__ == "__main__":
    df = extract("data/raw/cdr_logs.csv")
    print(f"CDR Extractor: {len(df)} entities extracted")
    print(df["Entity_Type"].value_counts().to_string())
