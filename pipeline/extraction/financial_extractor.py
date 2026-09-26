"""
CrimeNet AI — Financial Transaction Entity Extractor
Extracts accounts, mobiles, and suspicious flags from financial_txns.csv
"""

import pandas as pd


def extract(fin_path: str) -> pd.DataFrame:
    df = pd.read_csv(fin_path)
    records = []

    for _, row in df.iterrows():
        txn_id = row["TXN_ID"]
        date   = str(row.get("Transaction_DateTime", ""))[:10]
        flag   = str(row.get("Suspicious_Flag", "None")).strip()
        is_sus = flag != "None"

        for role, col in [("Sender", "Sender_Account"), ("Receiver", "Receiver_Account")]:
            acc = str(row.get(col, "")).strip()
            if not acc or acc in ("nan", "NULL", ""):
                continue
            records.append({
                "Entity_ID":    "",
                "Entity_Type":  "Account",
                "Entity_Value": acc,
                "Role":         role,
                "Mobile":       str(row.get("Mobile_Ref", "NULL")).strip(),
                "Source_File":  "Financial",
                "Source_ID":    txn_id,
                "Date":         date,
                "District":     str(row.get("Bank", "Unknown")),
                "Suspicious":   is_sus,
                "Flag":         flag,
            })

        # Mobile reference
        mob = str(row.get("Mobile_Ref", "")).strip()
        if mob and mob not in ("NULL", "nan", ""):
            records.append({
                "Entity_ID":    "",
                "Entity_Type":  "Mobile",
                "Entity_Value": mob,
                "Role":         "TransactionMobile",
                "Mobile":       mob,
                "Source_File":  "Financial",
                "Source_ID":    txn_id,
                "Date":         date,
                "District":     str(row.get("Bank", "Unknown")),
                "Suspicious":   is_sus,
                "Flag":         flag,
            })

    result = pd.DataFrame(records)
    result["Entity_ID"] = [f"FIN-ENT-{i+1:06d}" for i in range(len(result))]
    sus = result.get("Suspicious", pd.Series([False]*len(result)))
    print(f"  Suspicious entity records: {sus.sum()}")
    return result


if __name__ == "__main__":
    df = extract("data/raw/financial_txns.csv")
    print(f"Financial Extractor: {len(df)} entities extracted")
    print(df["Entity_Type"].value_counts().to_string())
