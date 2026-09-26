"""
CIPHER — Bulk CSV Importer
Imports the 500-row FIR dataset into the system: one case per row via
core.case_manager.create_case(), plus one case_entities row per entity
found in that FIR's structured columns (complainant, victim, suspect,
associate, witness, vehicle, account, incident location).

Idempotent by design: re-running against the same CSV will not create
duplicate cases (create_case() already no-ops on an existing fir_id) and
will not duplicate that case's entities either, since we skip entity
attachment entirely for cases that already existed before this run.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import pandas as pd

from core.case_manager import add_case_entity, create_case
from core.case_access import record_related_fir_reference
from core.config import FIR_CSV

logger = logging.getLogger(__name__)

# Maps a (name_column, mobile_column) pair to the case_entities role that
# should be recorded for the person found there.
PERSON_COLUMNS: list[tuple[str, str | None, str]] = [
    ("Complainant_Name", "Complainant_Mobile", "complainant"),
    ("Victim_Name", "Victim_Mobile", "victim"),
    ("Suspect_Name", "Suspect_Mobile", "suspect"),
    ("Associate_Name", "Associate_Mobile", "associate"),
    ("Witness_Name", "Witness_Mobile", "witness"),
]


def _clean(value: Any) -> str | None:
    """Normalise a pandas cell to a stripped string, or None if it's
    missing/blank. NaN from pandas is a float, so isinstance-checking
    for float+isnan is the reliable way to catch it before str() turns
    it into the literal string 'nan'."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text if text else None


def import_row(row: pd.Series, username: str = "bulk_import") -> tuple[bool, int]:
    """
    Import a single FIR row: create the case (if new), attach its
    entities (only if the case was newly created this call, to avoid
    duplicate entity rows on re-import).

    Returns (case_created, entities_added).
    """
    fir_id = _clean(row.get("FIR_ID"))
    if not fir_id:
        logger.warning("Skipping row with missing FIR_ID: %s", dict(row))
        return False, 0

    fields = {k: _clean(v) for k, v in row.to_dict().items()}
    case_created = create_case(fir_id, fields, username=username)

    entities_added = 0
    if not case_created:
        # Case already existed before this import run — its entities were
        # already attached the first time, so skip to avoid duplicates.
        return False, 0

    # People (name + optional mobile)
    for name_col, mobile_col, role in PERSON_COLUMNS:
        name = _clean(row.get(name_col))
        if name:
            add_case_entity(
                fir_id, name, "person", role=role,
                confidence_tier="observed_fact", source="csv", username=username,
            )
            entities_added += 1

        mobile = _clean(row.get(mobile_col)) if mobile_col else None
        if mobile:
            add_case_entity(
                fir_id, mobile, "phone", role=role,
                confidence_tier="observed_fact", source="csv", username=username,
            )
            entities_added += 1

    # Vehicle
    vehicle = _clean(row.get("Vehicle_Number"))
    if vehicle:
        add_case_entity(
            fir_id, vehicle, "vehicle", role="vehicle",
            confidence_tier="observed_fact", source="csv", username=username,
        )
        entities_added += 1

    # Financial account
    account = _clean(row.get("Account_Number"))
    if account:
        add_case_entity(
            fir_id, account, "account", role="account",
            confidence_tier="observed_fact", source="csv", username=username,
        )
        entities_added += 1

    # Incident location
    location = _clean(row.get("Incident_Location"))
    if location:
        add_case_entity(
            fir_id, location, "location", role="location",
            confidence_tier="observed_fact", source="csv", username=username,
        )
        entities_added += 1

    return case_created, entities_added


def import_all(csv_path=FIR_CSV, username: str = "bulk_import") -> dict[str, int]:
    """
    Import every row in the FIR CSV. Safe to re-run — already-imported
    cases are skipped (see import_row).

    Returns a summary dict: total rows, cases created, cases skipped
    (already existed), entities added, rows skipped for missing FIR_ID.
    """
    df = pd.read_csv(csv_path)
    logger.info("Loaded %d FIR rows from %s", len(df), csv_path)

    summary = {
        "total_rows": len(df),
        "cases_created": 0,
        "cases_skipped_existing": 0,
        "rows_skipped_no_fir_id": 0,
        "entities_added": 0,
    }

    for _, row in df.iterrows():
        fir_id = _clean(row.get("FIR_ID"))
        if not fir_id:
            summary["rows_skipped_no_fir_id"] += 1
            continue

        created, entities_added = import_row(row, username=username)
        if created:
            summary["cases_created"] += 1
        else:
            summary["cases_skipped_existing"] += 1
        summary["entities_added"] += entities_added

    # Index only source-declared Related_FIR_ID values whose two case records
    # exist; never synthesize entity-to-entity relationships from this field.
    for _, row in df.iterrows():
        fir_id = _clean(row.get("FIR_ID"))
        related_fir_id = _clean(row.get("Related_FIR_ID"))
        if fir_id and related_fir_id:
            try:
                record_related_fir_reference(
                    fir_id,
                    related_fir_id,
                    username=username,
                )
            except ValueError:
                logger.warning("Skipping unsafe Related_FIR_ID on %s", fir_id)

    logger.info("Import complete: %s", summary)
    return summary


if __name__ == "__main__":
    import sys

    from core.db import init_db

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.path.insert(0, ".")

    init_db()

    print("Running bulk import of FIR dataset...")
    result = import_all()

    print("\n" + "=" * 60)
    print("  Import summary")
    print("=" * 60)
    for key, value in result.items():
        print(f"  {key}: {value}")
    print("=" * 60)