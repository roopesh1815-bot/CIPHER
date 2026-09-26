"""Alerts API: merges structural anomalies and temporal-burst alerts into one feed."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.config import ANOMALIES_CSV, TEMPORAL_ALERTS_CSV # adjust if your config module names this differently

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

ANOMALIES_PATH = ANOMALIES_CSV
TEMPORAL_ALERTS_PATH = TEMPORAL_ALERTS_CSV

AlertType = Literal["anomaly", "temporal_burst"]
Severity = Literal["Low", "Medium", "High", "Critical"]


class Alert(BaseModel):
    alert_id: str
    type: AlertType
    entity_label: str
    entity_type: Optional[str] = None
    severity: Severity
    detail: str
    case_ids: list[str] = []
    window_days: Optional[int] = None


def _severity_from_case_count(case_count: int) -> Severity:
    """temporal_alerts.csv has no Severity column, so derive one.
    Thresholds are a starting guess — tune Case_Count_In_Window cutoffs if needed."""
    if case_count >= 8:
        return "High"
    if case_count >= 5:
        return "Medium"
    return "Low"


def _load_anomaly_alerts() -> list[Alert]:
    if not ANOMALIES_PATH.exists():
        logger.warning("anomalies file not found at %s", ANOMALIES_PATH)
        return []
    df = pd.read_csv(ANOMALIES_PATH)
    alerts: list[Alert] = []
    for i, row in df.iterrows():
        alerts.append(
            Alert(
                alert_id=f"ANOM-{row['Canonical_ID']}-{i}",
                type="anomaly",
                entity_label=str(row["Label"]),
                entity_type=str(row["Entity_Type"]),
                severity=str(row["Severity"]),
                detail=f"{row['Anomaly_Type']}: {row['Anomaly_Detail']}",
                case_ids=[],
            )
        )
    return alerts


def _load_temporal_alerts() -> list[Alert]:
    if not TEMPORAL_ALERTS_PATH.exists():
        logger.warning("temporal alerts file not found at %s", TEMPORAL_ALERTS_PATH)
        return []
    df = pd.read_csv(TEMPORAL_ALERTS_PATH)
    alerts: list[Alert] = []
    for i, row in df.iterrows():
        case_ids = str(row["FIR_IDs"]).split("|") if pd.notna(row["FIR_IDs"]) else []
        case_count = int(row["Case_Count_In_Window"])
        alerts.append(
            Alert(
                alert_id=f"TEMP-{row['Entity']}-{i}",
                type="temporal_burst",
                entity_label=str(row["Entity"]),
                entity_type=None,
                severity=_severity_from_case_count(case_count),
                detail=str(row["Note"]),
                case_ids=case_ids,
                window_days=int(row["Window_Days"]),
            )
        )
    return alerts


def _load_all_alerts() -> list[Alert]:
    return _load_anomaly_alerts() + _load_temporal_alerts()


@router.get("", response_model=list[Alert])
def list_alerts(
    type: Optional[AlertType] = Query(None, description="Filter: anomaly or temporal_burst"),
    severity: Optional[Severity] = Query(None, description="Filter: Low, Medium, High, Critical"),
    search: Optional[str] = Query(None, description="Case-insensitive match on entity label or detail"),
):
    alerts = _load_all_alerts()

    if type:
        alerts = [a for a in alerts if a.type == type]
    if severity:
        alerts = [a for a in alerts if a.severity == severity]
    if search:
        needle = search.lower()
        alerts = [
            a for a in alerts
            if needle in a.entity_label.lower() or needle in a.detail.lower()
        ]

    # Highest severity first, so the most important alerts surface without extra clicks.
    severity_rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    alerts.sort(key=lambda a: severity_rank.get(a.severity, 4))
    return alerts


@router.get("/{alert_id}", response_model=Alert)
def get_alert(alert_id: str):
    for a in _load_all_alerts():
        if a.alert_id == alert_id:
            return a
    raise HTTPException(status_code=404, detail="Alert not found")
