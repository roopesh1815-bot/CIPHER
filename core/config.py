"""
CIPHER — Central Configuration
Single source of truth for every path, constant and environment value used
across the project. Never hardcode a path anywhere else — import from here.

All paths are resolved relative to this file's location, so the pipeline
works correctly regardless of the current working directory it's run from
(the folder is named "crimenet-ai" by mistake — never hardcode that name).
"""

import os
import re
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv not installed — .env values simply won't be loaded,
    # environment variables set another way still work fine.
    pass

# ---- project root --------------------------------------------------------
# core/config.py -> core/ -> project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---- top-level folders ----------------------------------------------------
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
CASES_DIR = DATA_DIR / "cases"
DB_DIR = DATA_DIR / "db"
OUTPUT_DIR = PROJECT_ROOT / "output"
DOCS_DIR = PROJECT_ROOT / "docs"
TESTS_DIR = PROJECT_ROOT / "tests"

# ---- raw input datasets ----------------------------------------------------
FIR_CSV = RAW_DIR / "fir_500.csv"
CDR_CSV = RAW_DIR / "cdr_logs.csv"
FINANCIAL_CSV = RAW_DIR / "financial_txns.csv"
SOCIAL_CSV = RAW_DIR / "social_media.csv"

# ---- processed / intelligence outputs --------------------------------------
ENTITIES_CSV = PROCESSED_DIR / "entities.csv"
CENTRALITY_CSV = PROCESSED_DIR / "centrality.csv"
COMMUNITIES_CSV = PROCESSED_DIR / "communities.csv"
COMMUNITIES_JSON = PROCESSED_DIR / "communities.json"
ANOMALIES_CSV = PROCESSED_DIR / "anomalies.csv"
LINK_PREDICTIONS_CSV = PROCESSED_DIR / "link_predictions.csv"
LINK_PREDICTIONS_JSON = PROCESSED_DIR / "link_predictions.json"
RISK_SCORES_CSV = PROCESSED_DIR / "risk_scores.csv"
RISK_SCORES_JSON = PROCESSED_DIR / "risk_scores.json"
CASE_SUMMARIES_CSV = PROCESSED_DIR / "case_summaries.csv"
CASE_SUMMARIES_JSON = PROCESSED_DIR / "case_summaries.json"
ENTITY_TIMELINES_JSON = PROCESSED_DIR / "entity_timelines.json"
TEMPORAL_ALERTS_CSV = PROCESSED_DIR / "temporal_alerts.csv"
CRIME_TYPE_TREND_CSV = PROCESSED_DIR / "crime_type_trend.csv"

# ---- graph exports ----------------------------------------------------------
GRAPH_JSON = OUTPUT_DIR / "graph.json"
GRAPH_GEXF = OUTPUT_DIR / "graph.gexf"
RELATIONSHIPS_CSV = OUTPUT_DIR / "relationships.csv"

# ---- database -----------------------------------------------------------------
DB_PATH = DB_DIR / "cipher.db"
DB_BACKUP_DIR = DB_DIR / "backups"

# ---- case folders -----------------------------------------------------------
CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_case_id(fir_id: str) -> str:
    """Validate a case identifier as one safe path component."""
    if not isinstance(fir_id, str) or not CASE_ID_PATTERN.fullmatch(fir_id):
        raise ValueError("Invalid case identifier")
    return fir_id


def case_folder(fir_id: str) -> Path:
    """Return the per-case folder path for a given FIR_ID, e.g. FIR-2026-00001."""
    validate_case_id(fir_id)
    root = CASES_DIR.resolve()
    folder = (root / fir_id).resolve()
    try:
        folder.relative_to(root)
    except ValueError as error:
        raise ValueError("Case folder escapes the configured case storage root") from error
    return folder

def case_record_path(fir_id: str) -> Path:
    return case_folder(fir_id) / "case_record.json"

def case_documents_original_dir(fir_id: str) -> Path:
    return case_folder(fir_id) / "documents" / "original"

def case_documents_scans_dir(fir_id: str) -> Path:
    return case_folder(fir_id) / "documents" / "scans"

def case_ocr_text_dir(fir_id: str) -> Path:
    return case_folder(fir_id) / "ocr_text"

def case_notes_dir(fir_id: str) -> Path:
    return case_folder(fir_id) / "notes"

def case_timeline_path(fir_id: str) -> Path:
    return case_folder(fir_id) / "timeline.json"

def case_audit_log_path(fir_id: str) -> Path:
    return case_folder(fir_id) / "audit_log.jsonl"

# ---- upload / OCR safety limits (F5) -----------------------------------------
ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".txt", ".docx"}
MAX_UPLOAD_SIZE_MB = 20
ACCESS_GRANT_LIFETIME_MINUTES = 30
ACCESS_REQUEST_LIFETIME_DAYS = 7

# ---- auth / audit (Phase 3) --------------------------------------------------
ROLE_INVESTIGATOR = "Field Investigator"
ROLE_ADMIN = "Admin"
VALID_ROLES = {ROLE_INVESTIGATOR, ROLE_ADMIN}

# ---- environment-sourced values (.env) ----------------------------------------
# Secrets/keys/anything environment-specific goes here, read once, used
# everywhere else via this module — never read os.environ directly elsewhere.
SECRET_KEY = os.getenv("CIPHER_SECRET_KEY", "dev-only-change-me")
DEBUG = os.getenv("CIPHER_DEBUG", "false").lower() == "true"

# ---- wording discipline (F17) --------------------------------------------------
# Central place for the neutral vocabulary used across all UI text, so pages
# don't drift into "criminal"/"guilty"/"confirmed" phrasing.
NEUTRAL_TERMS = {
    "priority_score_label": "Priority score (for investigator review)",
    "suggested_link_label": "AI-suggested link (unconfirmed)",
    "suspect_status_label": "Reported / Alleged",
}

# ---- ensure required folders exist at import time ------------------------------
for _dir in (
    RAW_DIR, PROCESSED_DIR, CASES_DIR, DB_DIR, DB_BACKUP_DIR,
    OUTPUT_DIR, DOCS_DIR,
):
    _dir.mkdir(parents=True, exist_ok=True)