"""
CIPHER API — Risk Scoring endpoint.
Serves data/processed/risk_scores.json (entity-level priority scores,
produced by pipeline/intelligence/risk_scorer.py).
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from api.security import get_current_user
from core.config import RISK_SCORES_JSON

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/risk", tags=["risk"])

_risk_cache: list[dict] | None = None


def _load_risk_scores() -> list[dict]:
    global _risk_cache
    if _risk_cache is None:
        if not RISK_SCORES_JSON.exists():
            raise HTTPException(
                status_code=404,
                detail="risk_scores.json not found — run run_pipeline.py first",
            )
        with open(RISK_SCORES_JSON, encoding="utf-8") as f:
            _risk_cache = json.load(f)
    return _risk_cache


@router.get("")
def list_risk_scores(
    user: dict = Depends(get_current_user),
    entity_type: str | None = Query(None),
    risk_tier: str | None = Query(None, description="Low/Medium/High/Critical"),
    min_score: float | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Entities ranked by Risk_Score descending (matches Risk_Rank already
    computed by risk_scorer.py, but re-sorted here so filters don't break
    the ordering)."""
    scores = _load_risk_scores()

    filtered = scores
    if entity_type:
        filtered = [s for s in filtered if s.get("Entity_Type", "").lower() == entity_type.lower()]
    if risk_tier:
        filtered = [s for s in filtered if s.get("Risk_Tier", "").lower() == risk_tier.lower()]
    if min_score is not None:
        filtered = [s for s in filtered if (s.get("Risk_Score") or 0) >= min_score]
    if search:
        s_lower = search.lower()
        filtered = [s for s in filtered if s_lower in (s.get("Label") or "").lower()]

    filtered = sorted(filtered, key=lambda s: s.get("Risk_Score") or 0, reverse=True)
    total = len(filtered)
    page = filtered[offset : offset + limit]

    tier_counts: dict[str, int] = {}
    for s in scores:
        tier = s.get("Risk_Tier", "Unknown")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    return {"scores": page, "total": total, "limit": limit, "offset": offset, "tier_distribution": tier_counts}


@router.get("/{canonical_id}")
def get_risk_detail(canonical_id: str, user: dict = Depends(get_current_user)):
    """Full risk detail for one entity."""
    scores = _load_risk_scores()
    entity = next((s for s in scores if s.get("Canonical_ID") == canonical_id), None)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity {canonical_id} not found")
    return entity