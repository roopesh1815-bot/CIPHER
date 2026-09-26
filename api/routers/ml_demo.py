"""Read-only API for the isolated synthetic ML demonstration."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends

from api.security import get_current_user

router = APIRouter(prefix="/api/ml-demo", tags=["ml-demo"])
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = PROJECT_ROOT / "models" / "ml_experiment" / "runs"
DISPLAY_LIMIT = 100
LIMITATION = (
    "This is a controlled synthetic ML demonstration. Performance on this "
    "synthetic dataset does not establish real-world predictive validity."
)
EXPLANATION = (
    "Potential relationship identified by the synthetic ML demonstration. "
    "Requires investigator review."
)
NOTICE = (
    "This is a synthetic analytical demonstration and is not evidence or proof "
    "of wrongdoing."
)


def _latest_run() -> Path | None:
    if not RUNS_DIR.is_dir():
        return None
    runs = [
        path for path in RUNS_DIR.iterdir()
        if path.is_dir()
        and (path / "metadata.json").is_file()
        and (path / "evaluation.json").is_file()
        and (path / "predictions.csv").is_file()
    ]
    return max(runs, key=lambda path: path.name, default=None)


@router.get("")
def get_ml_demo(user: dict = Depends(get_current_user)):
    run_dir = _latest_run()
    if run_dir is None:
        return {
            "available": False,
            "limitation": LIMITATION,
            "explanation": EXPLANATION,
            "notice": NOTICE,
            "message": "No synthetic ML demonstration run is available.",
            "predictions": [],
        }

    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    evaluation = json.loads((run_dir / "evaluation.json").read_text(encoding="utf-8"))
    predictions = pd.read_csv(run_dir / "predictions.csv").head(DISPLAY_LIMIT)
    return {
        "available": True,
        "run_id": metadata["run_id"],
        "model_type": metadata["model_type"],
        "model_version": metadata["model_version"],
        "dataset_version": metadata["dataset_version"],
        "split_counts": metadata["split_counts"],
        "evaluation": evaluation,
        "limitation": metadata.get("limitation", LIMITATION),
        "explanation": EXPLANATION,
        "notice": NOTICE,
        "predictions": predictions.to_dict(orient="records"),
    }
