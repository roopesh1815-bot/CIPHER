"""
CrimeNet AI — Entity Resolver
Merges duplicate entities across all 4 sources into one clean entity table
Key: same mobile number OR same name = same person
"""

import pandas as pd
from collections import defaultdict


def resolve(all_entities: pd.DataFrame) -> pd.DataFrame:
    """
    Deduplicate and merge entities.
    Returns a clean DataFrame with one row per unique entity.
    """
    df = all_entities.copy()

    # ── 1. Normalize values ───────────────────────────────────
    df["Entity_Value"] = df["Entity_Value"].str.strip().str.title()
    df["Mobile"]       = df["Mobile"].str.strip()

    # ── 2. Build canonical ID map ─────────────────────────────
    # For People: group by mobile (same mobile = same person)
    # For Mobiles: group by value
    # For Vehicles / Accounts / Locations: group by value

    canonical = {}   # entity_value -> canonical_id
    counter   = defaultdict(int)

    def get_canon_id(etype, value):
        key = f"{etype}::{value}"
        if key not in canonical:
            counter[etype] += 1
            canonical[key] = f"{etype[:3].upper()}-{counter[etype]:04d}"
        return canonical[key]

    # ── 3. Assign canonical IDs ───────────────────────────────
    # Mobile-based linking for Person entities
    mobile_to_canon = {}   # mobile -> canonical person id

    person_rows = df[df["Entity_Type"] == "Person"].copy()
    for _, row in person_rows.iterrows():
        mob = row["Mobile"]
        val = row["Entity_Value"]
        if mob not in ("NULL", "nan", "", None) and mob not in mobile_to_canon:
            cid = get_canon_id("Person", val)
            mobile_to_canon[mob] = cid
            canonical[f"Person::{val}"] = cid

    # ── 4. Assign to all rows ─────────────────────────────────
    canon_ids = []
    for _, row in df.iterrows():
        etype = row["Entity_Type"]
        val   = row["Entity_Value"]
        mob   = row["Mobile"]

        if etype == "Person":
            # Use mobile link if available
            if mob in mobile_to_canon:
                cid = mobile_to_canon[mob]
            else:
                cid = get_canon_id("Person", val)
        elif etype == "Mobile":
            # Mobile entity: check if it links to a known person
            if val in mobile_to_canon:
                cid = mobile_to_canon[val]
            else:
                cid = get_canon_id("Mobile", val)
        else:
            cid = get_canon_id(etype, val)

        canon_ids.append(cid)

    df["Canonical_ID"] = canon_ids

    # ── 5. Count source appearances ───────────────────────────
    source_counts = df.groupby("Canonical_ID")["Source_File"].nunique().rename("Source_Count")
    df = df.merge(source_counts, on="Canonical_ID", how="left")

    # ── 6. Aggregate into one row per canonical entity ────────
    agg = df.groupby("Canonical_ID").agg(
        Entity_Type  = ("Entity_Type",  "first"),
        Entity_Value = ("Entity_Value", "first"),
        Mobile       = ("Mobile",       "first"),
        Sources      = ("Source_File",  lambda x: "|".join(sorted(set(x)))),
        Source_Count = ("Source_Count", "first"),
        FIR_Count    = ("Source_File",  lambda x: (x == "FIR").sum()),
        CDR_Count    = ("Source_File",  lambda x: (x == "CDR").sum()),
        Fin_Count    = ("Source_File",  lambda x: (x == "Financial").sum()),
        Soc_Count    = ("Source_File",  lambda x: (x == "SocialMedia").sum()),
        First_Seen   = ("Date",         "min"),
        Last_Seen    = ("Date",         "max"),
        Roles        = ("Role",         lambda x: "|".join(sorted(set(x)))),
    ).reset_index()

    # ── 7. Cross-verified flag ────────────────────────────────
    agg["Cross_Verified"] = agg["Source_Count"] >= 2

    print(f"  Entity resolver: {len(df)} raw → {len(agg)} unique entities")
    print(f"  Cross-verified (2+ sources): {agg['Cross_Verified'].sum()}")

    return agg


if __name__ == "__main__":
    import os, sys
    sys.path.insert(0, "pipeline/extraction")
    import fir_extractor, cdr_extractor, financial_extractor, social_extractor

    e1 = fir_extractor.extract("data/raw/fir_500.csv")
    e2 = cdr_extractor.extract("data/raw/cdr_logs.csv")
    e3 = financial_extractor.extract("data/raw/financial_txns.csv")
    e4 = social_extractor.extract("data/raw/social_media.csv")

    all_ents = pd.concat([e1, e2, e3, e4], ignore_index=True)
    resolved = resolve(all_ents)
    resolved.to_csv("data/processed/entities.csv", index=False)
    print(resolved["Entity_Type"].value_counts().to_string())
