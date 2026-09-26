"""
CIPHER API — Case Manager endpoints.
Serves data/processed/case_summaries.json (per-case risk/narrative,
produced by pipeline/intelligence/case_summariser.py) merged with the
`cases` DB table (status, district, folder_path) and case_entities.
"""

import csv
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from api.security import get_current_user
from core.artifact_cache import FileArtifactCache
from core.config import CASE_SUMMARIES_JSON, ENTITIES_CSV
from core.db import fetch_all, fetch_one

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cases", tags=["cases"])

_summaries_cache: FileArtifactCache[dict[str, dict]] = FileArtifactCache()
_entity_identity_cache: FileArtifactCache[dict[str, dict]] = FileArtifactCache()

_ENTITY_TYPE_ALIASES = {
    "phone": "mobile",
    "celltower": "cell tower",
    "socialhandle": "social handle",
}


def _load_entity_identities() -> dict[str, dict]:
    """Load current canonical IDs and labels from the resolved-entity output."""
    if not ENTITIES_CSV.exists():
        raise HTTPException(
            status_code=503,
            detail="entities.csv not found — run entity resolution first",
        )

    def load_identities(path: Path) -> dict[str, dict]:
        with path.open(encoding="utf-8-sig", newline="") as entity_file:
            rows = csv.DictReader(entity_file)
            return {
                row["Canonical_ID"]: {
                    "entity_label": row["Entity_Value"],
                    "entity_type": row["Entity_Type"],
                }
                for row in rows
            }

    return _entity_identity_cache.load(ENTITIES_CSV, load_identities)


def _normalize_entity_type(value: object) -> str:
    entity_type = str(value or "").strip().casefold()
    return _ENTITY_TYPE_ALIASES.get(entity_type, entity_type)


def _load_summaries() -> dict[str, dict]:
    """Load case summaries keyed by FIR_ID and refresh after file changes."""
    try:
        return _summaries_cache.load(
            CASE_SUMMARIES_JSON,
            lambda path: {
                row["FIR_ID"]: row
                for row in json.loads(path.read_text(encoding="utf-8"))
            },
        )
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail="case_summaries.json not found — run run_pipeline.py first",
        ) from error


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


@router.get("/entity/{canonical_id}")
def get_entity_cases(
    canonical_id: str,
    user: dict = Depends(get_current_user),
):
    """Return existing case-entity records associated with a canonical entity."""
    identities = _load_entity_identities()
    identity = identities.get(canonical_id)
    if identity is None:
        raise HTTPException(status_code=404, detail=f"Entity {canonical_id} not found")

    entity_label = identity["entity_label"]
    entity_type = _normalize_entity_type(identity["entity_type"])
    ambiguous_ids = [
        entity_id
        for entity_id, candidate in identities.items()
        if entity_id != canonical_id
        and candidate["entity_label"].casefold() == entity_label.casefold()
        and _normalize_entity_type(candidate["entity_type"]) == entity_type
    ]
    if ambiguous_ids:
        raise HTTPException(
            status_code=409,
            detail=f"Case associations for entity {canonical_id} are ambiguous by label and type",
        )

    records = fetch_all(
        """SELECT c.fir_id, c.crime_type, c.district, c.status, c.fir_date,
                  ce.entity_label, ce.entity_type, ce.role,
                  ce.confidence_tier, ce.source
           FROM case_entities AS ce
           JOIN cases AS c ON c.fir_id = ce.fir_id"""
    )
    matching_records = [
        record
        for record in records
        if str(record.get("entity_label") or "").casefold() == entity_label.casefold()
        and _normalize_entity_type(record.get("entity_type")) == entity_type
    ]
    cases_by_id: dict[str, dict] = {}
    for record in matching_records:
        fir_id = record["fir_id"]
        case_record = cases_by_id.setdefault(
            fir_id,
            {
                "fir_id": fir_id,
                "crime_type": record.get("crime_type"),
                "district": record.get("district"),
                "status": record.get("status"),
                "fir_date": record.get("fir_date"),
                "entity_records": [],
            },
        )
        case_record["entity_records"].append(
            {
                "entity_label": record.get("entity_label"),
                "entity_type": record.get("entity_type"),
                "role": record.get("role"),
                "confidence_tier": record.get("confidence_tier"),
                "source": record.get("source"),
            }
        )
    associated_cases = sorted(
        cases_by_id.values(),
        key=lambda case_record: (case_record.get("fir_date") or "", case_record["fir_id"]),
        reverse=True,
    )

    return {
        "canonical_id": canonical_id,
        "entity_label": entity_label,
        "entity_type": identity["entity_type"],
        "cases": associated_cases,
        "total": len(associated_cases),
    }


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