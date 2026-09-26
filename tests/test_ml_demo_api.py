import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from api.routers import ml_demo
from api.security import get_current_user


class MlDemoApiTests(unittest.TestCase):
    def test_missing_run_returns_unavailable_without_generating_data(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(ml_demo, "RUNS_DIR", Path(directory)):
                response = ml_demo.get_ml_demo(user={
                    "username": "investigator",
                    "role": "Field Investigator",
                    "is_active": 1,
                })
        self.assertFalse(response["available"])
        self.assertEqual(response["predictions"], [])
        self.assertIn("synthetic ML demonstration", response["limitation"])
        self.assertIn("Requires investigator review", response["explanation"])
        self.assertIn("not evidence or proof", response["notice"])

    def test_endpoint_requires_authentication(self):
        route = next(
            route for route in ml_demo.router.routes
            if getattr(route, "path", None) == "/api/ml-demo"
        )
        self.assertTrue(any(
            dependency.call is get_current_user
            for dependency in route.dependant.dependencies
        ))

    def test_api_returns_only_isolated_synthetic_run_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run-001"
            run_dir.mkdir()
            metadata = {
                "run_id": "run-001",
                "model_type": "StandardScaler + LogisticRegression",
                "model_version": "temporal-logistic-regression-v1",
                "dataset_version": "synthetic-network-v1",
                "split_counts": {},
                "limitation": ml_demo.LIMITATION,
            }
            (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            (run_dir / "evaluation.json").write_text(json.dumps({"test": {}}), encoding="utf-8")
            pd.DataFrame([{
                "source_entity_id": "SYN-E0001",
                "target_entity_id": "SYN-E0002",
                "model_score": 0.7,
                "status": "ML_SUGGESTED_UNCONFIRMED",
            }]).to_csv(run_dir / "predictions.csv", index=False)
            with patch.object(ml_demo, "RUNS_DIR", Path(directory)):
                payload = ml_demo.get_ml_demo(user={"username": "investigator"})
        self.assertTrue(payload["available"])
        self.assertEqual(payload["predictions"][0]["status"], "ML_SUGGESTED_UNCONFIRMED")
        self.assertTrue(payload["predictions"][0]["source_entity_id"].startswith("SYN-"))
