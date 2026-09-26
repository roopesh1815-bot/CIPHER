"""
CIPHER — Key Influencers Router
Exposes centrality.csv (Degree, Betweenness, PageRank, Closeness, and the
composite Influence_Score) as a filterable, paginated API for the
"Key Influencers" dashboard page — directly answers the SIH requirement
to "identify key individuals who play influential roles."
"""

from fastapi import APIRouter, Depends, HTTPException, Query
import pandas as pd

from api.security import get_current_user  # matches the pattern used in cases.py/graph.py

router = APIRouter(prefix="/api/influencers", tags=["influencers"])

CENTRALITY_PATH = "data/processed/centrality.csv"


def _load() -> pd.DataFrame:
    try:
        return pd.read_csv(CENTRALITY_PATH)
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="centrality.csv not found — run the pipeline first (python -m pipeline.run_pipeline)",
        )


@router.get("/entity-types")
def entity_types(user: dict = Depends(get_current_user)):
    df = _load()
    return {"entity_types": sorted(df["Entity_Type"].dropna().unique().tolist())}


@router.get("")
def list_influencers(
    user: dict = Depends(get_current_user),
    entity_type: str = Query(None),
    search: str = Query(None),
    min_score: float = Query(None, description="Minimum Influence_Score (0-100)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    df = _load()

    if entity_type:
        df = df[df["Entity_Type"] == entity_type]
    if search:
        df = df[df["Label"].str.contains(search, case=False, na=False)]
    if min_score is not None:
        df = df[df["Influence_Score"] >= min_score]

    df = df.sort_values("Influence_Score", ascending=False)
    total = len(df)
    page = df.iloc[offset: offset + limit]

    return {
        "total": total,
        "influencers": page.to_dict(orient="records"),
    }


@router.get("/{canonical_id}")
def influencer_detail(canonical_id: str, user: dict = Depends(get_current_user)):
    df = _load()
    match = df[df["Canonical_ID"] == canonical_id]
    if match.empty:
        raise HTTPException(status_code=404, detail="Entity not found in centrality data")
    return match.iloc[0].to_dict()