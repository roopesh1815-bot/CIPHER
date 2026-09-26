"""
CIPHER API — Case Manager endpoints.
Serves data/processed/case_summaries.json (per-case risk/narrative,
produced by pipeline/intelligence/case_summariser.py) merged with the
`cases` DB table (status, district, folder_path) and case_entities.
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from api.security import get_current_user
from core.config import CASE_SUMMARIES_JSON
from core.db import fetch_all, fetch_one

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cases", tags=["cases"])

_summaries_cache: dict[str, dict] | None = None


def _load_summaries() -> dict[str, dict]:
    """Load case_summaries.json once, keyed by FIR_ID, cached in memory
    (same pattern as api/routers/graph.py — refreshed only by re-running
    the pipeline, not on every request)."""
    global _summaries_cache
    if _summaries_cache is None:
        if not CASE_SUMMARIES_JSON.exists():
            raise HTTPException(
                status_code=404,
                detail="case_summaries.json not found — run run_pipeline.py first",
            )
        with open(CASE_SUMMARIES_JSON, encoding="utf-8") as f:
            rows = json.load(f)
        _summaries_cache = {row["FIR_ID"]: row for row in rows}
    return _summaries_cache


def _narrative_preview(narrative: str, max_len: int = 160) -> str:
    narrative = narrative or ""
    return narrative if len(narrative) <= max_len else narrative[:max_len].rstrip() + "…"


@router.get("")
def list_cases(
    user: dict = Depends(get_current_user),
    risk_tier: str | None = Query(None, description="Filter by Low/Medium/High/Critical"),
    crime_type: str | None = Query(None, description="Case-insensitive substring match"),
    search: str | None = Query(None, description="Matches FIR ID, location or narrative"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Merged case list: DB row (status, district, folder_path) + summary
    (risk tier/score, crime type, narrative preview). Sorted by risk
    score descending by default, so the highest-priority cases surface
    first — matches the investigator workflow this page is for.
    """
    summaries = _load_summaries()
    db_rows = {row["fir_id"]: row for row in fetch_all("SELECT * FROM cases")}

    merged = []
    for fir_id, summary in summaries.items():
        db_row = db_rows.get(fir_id, {})

        if risk_tier and summary.get("Lead_Risk_Tier", "").lower() != risk_tier.lower():
            continue
        if crime_type and crime_type.lower() not in (summary.get("Crime_Type") or "").lower():
            continue
        if search:
            haystack = " ".join(
                str(v) for v in (fir_id, summary.get("Location"), summary.get("Narrative"))
            ).lower()
            if search.lower() not in haystack:
                continue

        merged.append(
            {
                "fir_id": fir_id,
                "crime_type": summary.get("Crime_Type"),
                "location": summary.get("Location"),
                "date": summary.get("Date"),
                "status": db_row.get("status", "Unknown"),
                "district": db_row.get("district"),
                "risk_score": summary.get("Lead_Risk_Score"),
                "risk_tier": summary.get("Lead_Risk_Tier"),
                "num_anomalies": summary.get("Num_Anomalies", 0),
                "narrative_preview": _narrative_preview(summary.get("Narrative", "")),
            }
        )

    merged.sort(key=lambda c: c["risk_score"] or 0, reverse=True)
    total = len(merged)
    page = merged[offset : offset + limit]

    return {"cases": page, "total": total, "limit": limit, "offset": offset}


@router.get("/crime-types")
def get_crime_types(user: dict = Depends(get_current_user)):
    """Distinct crime types, for populating a filter dropdown."""
    summaries = _load_summaries()
    types = sorted({s.get("Crime_Type", "Unknown") for s in summaries.values()})
    return {"crime_types": types}


@router.get("/{fir_id}")
def get_case_detail(fir_id: str, user: dict = Depends(get_current_user)):
    """Full detail for one case: DB row, case_record.json fields, full
    narrative, and every entity attached via case_entities — the last of
    these is what a future case-scoped graph view will seed from."""
    db_row = fetch_one("SELECT * FROM cases WHERE fir_id = ?", (fir_id,))
    if db_row is None:
        raise HTTPException(status_code=404, detail=f"Case {fir_id} not found")

    summaries = _load_summaries()
    summary = summaries.get(fir_id, {})

    record = {}
    folder_path = db_row.get("folder_path")
    if folder_path:
        record_path = Path(folder_path) / "case_record.json"
        if record_path.exists():
            record = json.loads(record_path.read_text(encoding="utf-8"))

    entities = fetch_all(
        "SELECT * FROM case_entities WHERE fir_id = ? ORDER BY role, entity_type", (fir_id,)
    )

    return {
        "case": db_row,
        "summary": summary,
        "record": record,
        "entities": entities,
    }