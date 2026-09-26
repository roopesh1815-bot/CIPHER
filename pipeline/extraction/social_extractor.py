"""
CrimeNet AI — Social Media Entity Extractor
Extracts mentioned names, mobiles, vehicles, locations from social_media.csv
"""

import pandas as pd
import re


def extract(social_path: str) -> pd.DataFrame:
    df = pd.read_csv(social_path)
    records = []

    for _, row in df.iterrows():
        post_id  = row["POST_ID"]
        date     = str(row.get("Post_DateTime", ""))[:10]
        platform = row.get("Platform", "Unknown")
        handle   = row.get("Handle",   "Unknown")
        text     = str(row.get("Post_Text", ""))

        # ── Mentioned Name ────────────────────────────────────
        name = str(row.get("Mentioned_Name", "NULL")).strip()
        if name not in ("NULL", "nan", ""):
            records.append({
                "Entity_ID":    "",
                "Entity_Type":  "Person",
                "Entity_Value": name,
                "Role":         "SocialMention",
                "Mobile":       "NULL",
                "Source_File":  "SocialMedia",
                "Source_ID":    post_id,
                "Date":         date,
                "District":     platform,
            })

        # ── Mentioned Mobile ──────────────────────────────────
        mob = str(row.get("Mentioned_Mobile", "NULL")).strip()
        if mob not in ("NULL", "nan", ""):
            records.append({
                "Entity_ID":    "",
                "Entity_Type":  "Mobile",
                "Entity_Value": mob,
                "Role":         "SocialMention",
                "Mobile":       mob,
                "Source_File":  "SocialMedia",
                "Source_ID":    post_id,
                "Date":         date,
                "District":     platform,
            })

        # ── Mentioned Vehicle ─────────────────────────────────
        veh = str(row.get("Mentioned_Vehicle", "NULL")).strip()
        if veh not in ("NULL", "nan", ""):
            records.append({
                "Entity_ID":    "",
                "Entity_Type":  "Vehicle",
                "Entity_Value": veh,
                "Role":         "SocialMention",
                "Mobile":       "NULL",
                "Source_File":  "SocialMedia",
                "Source_ID":    post_id,
                "Date":         date,
                "District":     platform,
            })

        # ── Location ─────────────────────────────────────────
        loc = str(row.get("Mentioned_Location", "NULL")).strip()
        if loc not in ("NULL", "nan", ""):
            records.append({
                "Entity_ID":    "",
                "Entity_Type":  "Location",
                "Entity_Value": loc,
                "Role":         "SocialMention",
                "Mobile":       "NULL",
                "Source_File":  "SocialMedia",
                "Source_ID":    post_id,
                "Date":         date,
                "District":     platform,
            })

        # ── Regex: extra mobiles in text ──────────────────────
        found = re.findall(r"\b9\d{9}\b", text)
        for m in set(found):
            if m != mob:
                records.append({
                    "Entity_ID":    "",
                    "Entity_Type":  "Mobile",
                    "Entity_Value": m,
                    "Role":         "TextMention",
                    "Mobile":       m,
                    "Source_File":  "SocialMedia",
                    "Source_ID":    post_id,
                    "Date":         date,
                    "District":     platform,
                })

        # ── Post author handle as entity ──────────────────────
        records.append({
            "Entity_ID":    "",
            "Entity_Type":  "SocialHandle",
            "Entity_Value": handle,
            "Role":         "Author",
            "Mobile":       "NULL",
            "Source_File":  "SocialMedia",
            "Source_ID":    post_id,
            "Date":         date,
            "District":     platform,
        })

    result = pd.DataFrame(records)
    result["Entity_ID"] = [f"SOC-ENT-{i+1:06d}" for i in range(len(result))]
    return result


if __name__ == "__main__":
    df = extract("data/raw/social_media.csv")
    print(f"Social Extractor: {len(df)} entities extracted")
    print(df["Entity_Type"].value_counts().to_string())
