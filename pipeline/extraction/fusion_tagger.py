"""
CrimeNet AI — Fusion Tagger
Tags entities confirmed across 2+ independent sources with a Cross-Verified badge
This directly addresses PS-26189: "data fragmented across multiple systems"
"""

import pandas as pd

from core.spiderweb_center import normalize_fusion_badge


BADGE_LEVELS = {
    4: "🔗 Quad-Verified",
    3: "🔗 Triple-Verified",
    2: "🔗 Cross-Verified",
    1: "📄 Single-Source",
}


def tag(entities_path: str) -> pd.DataFrame:
    df = pd.read_csv(entities_path)

    # Assign badge level
    def badge(row):
        sc = int(row.get("Source_Count", 1))
        value = BADGE_LEVELS.get(sc, BADGE_LEVELS[1])
        if not normalize_fusion_badge(value):
            raise ValueError(f"Unsupported fusion badge: {value}")
        return value

    df["Fusion_Badge"]   = df.apply(badge, axis=1)
    df["Is_CrossVerified"] = df["Source_Count"] >= 2

    # Risk hint based on roles + cross verification
    def risk_hint(row):
        roles = str(row.get("Roles", ""))
        hints = []
        if "Suspect" in roles:
            hints.append("Named as suspect")
        if row["Is_CrossVerified"]:
            hints.append("Confirmed across sources")
        if row.get("CDR_Count", 0) > 0 and row.get("Fin_Count", 0) > 0:
            hints.append("CDR + Financial overlap")
        if row.get("Soc_Count", 0) > 0:
            hints.append("Social media mention")
        return "; ".join(hints) if hints else "No flags"

    df["Risk_Hint"] = df.apply(risk_hint, axis=1)

    summary = df["Fusion_Badge"].value_counts()
    print(f"  Fusion Tagger results:")
    for badge, count in summary.items():
        print(f"    {badge}: {count}")

    return df


if __name__ == "__main__":
    df = tag("data/processed/entities.csv")
    df.to_csv("data/processed/entities.csv", index=False)
    print(f"\nFusion tags applied to {len(df)} entities")
    print(df[df["Is_CrossVerified"]][["Entity_Value","Entity_Type","Sources","Fusion_Badge"]].head(10).to_string())
