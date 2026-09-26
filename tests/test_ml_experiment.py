import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import networkx as nx
import pandas as pd

from ml_experiment import temporal_link_demo as demo


class SyntheticDatasetTests(unittest.TestCase):
    def test_generation_is_reproducible_and_uses_only_synthetic_ids(self):
        first = demo.generate_events(seed=demo.RANDOM_SEED)
        second = demo.generate_events(seed=demo.RANDOM_SEED)
        self.assertEqual(first, second)
        self.assertEqual(len(first), demo.MONTH_COUNT * demo.EVENTS_PER_MONTH)
        self.assertTrue(all(row["source_entity_id"].startswith("SYN-") for row in first))
        self.assertTrue(all(row["target_entity_id"].startswith("SYN-") for row in first))
        self.assertTrue(all("group" not in key.lower() for key in first[0]))

    def test_dataset_schema_validation_rejects_non_synthetic_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.csv"
            path.write_text(
                "event_id,source_entity_id,target_entity_id,timestamp,event_type\n"
                "E1,PER-1,SYN-E0002,2024-01-01T00:00:00,synthetic_interaction\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                demo.load_events(path)

    def test_dataset_write_once_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "dataset"
            metadata = demo.write_dataset_once(folder)
            self.assertEqual(metadata["random_seed"], 26189)
            self.assertTrue((folder / "events.csv").is_file())
            with self.assertRaises(FileExistsError):
                demo.write_dataset_once(folder)


class TemporalFeatureTests(unittest.TestCase):
    def test_temporal_split_has_chronological_purging_gaps(self):
        rows = []
        for month in pd.period_range("2024-01", "2025-12", freq="M"):
            rows.append({
                "origin_month": str(month),
                "prediction_period": str(month + 1),
                "source_entity_id": "SYN-E0001",
                "target_entity_id": "SYN-E0002",
                **{feature: 0.0 for feature in demo.FEATURE_NAMES},
                "label": 0,
            })
        splits = demo.chronological_split(pd.DataFrame(rows))
        self.assertEqual(
            set(splits["train"]["origin_month"]),
            {f"2024-{month:02d}" for month in range(3, 13)},
        )
        self.assertEqual(
            set(splits["validation"]["origin_month"]),
            {f"2025-{month:02d}" for month in range(2, 6)},
        )
        self.assertEqual(
            set(splits["test"]["origin_month"]),
            {f"2025-{month:02d}" for month in range(7, 12)},
        )
        self.assertTrue(
            set(splits["train"]["prediction_period"]).isdisjoint(
                splits["validation"]["prediction_period"]
            )
        )
        self.assertTrue(
            set(splits["validation"]["prediction_period"]).isdisjoint(
                splits["test"]["prediction_period"]
            )
        )

    def test_future_events_do_not_change_features_before_cutoff(self):
        historical = [
            {"event_id": "1", "source_entity_id": "SYN-E0001", "target_entity_id": "SYN-E0003", "timestamp": "2024-01-10T00:00:00", "event_type": "synthetic_interaction"},
            {"event_id": "2", "source_entity_id": "SYN-E0002", "target_entity_id": "SYN-E0003", "timestamp": "2024-01-11T00:00:00", "event_type": "synthetic_interaction"},
        ]
        future = {
            "event_id": "3",
            "source_entity_id": "SYN-E0001",
            "target_entity_id": "SYN-E0002",
            "timestamp": "2024-04-10T00:00:00",
            "event_type": "synthetic_interaction",
        }
        before = demo.build_temporal_samples(historical)
        after = demo.build_temporal_samples([*historical, future])
        pair_before = before[
            (before["origin_month"] == "2024-03")
            & (before["source_entity_id"] == "SYN-E0001")
            & (before["target_entity_id"] == "SYN-E0002")
        ].iloc[0]
        pair_after = after[
            (after["origin_month"] == "2024-03")
            & (after["source_entity_id"] == "SYN-E0001")
            & (after["target_entity_id"] == "SYN-E0002")
        ].iloc[0]
        self.assertEqual(pair_before[demo.FEATURE_NAMES].to_dict(), pair_after[demo.FEATURE_NAMES].to_dict())
        self.assertEqual(pair_before["label"], 0)
        self.assertEqual(pair_after["label"], 1)

    def test_pair_generation_and_label_construction(self):
        events = [
            {"event_id": "1", "source_entity_id": "SYN-E0001", "target_entity_id": "SYN-E0003", "timestamp": "2024-01-10T00:00:00", "event_type": "synthetic_interaction"},
            {"event_id": "2", "source_entity_id": "SYN-E0002", "target_entity_id": "SYN-E0003", "timestamp": "2024-01-11T00:00:00", "event_type": "synthetic_interaction"},
            {"event_id": "3", "source_entity_id": "SYN-E0001", "target_entity_id": "SYN-E0002", "timestamp": "2024-04-10T00:00:00", "event_type": "synthetic_interaction"},
        ]
        graph = nx.Graph()
        graph.add_edges_from([
            ("SYN-E0001", "SYN-E0003"),
            ("SYN-E0002", "SYN-E0003"),
        ])
        self.assertIn(("SYN-E0001", "SYN-E0002"), demo._two_hop_pairs(graph))
        samples = demo.build_temporal_samples(events)
        positive = samples[
            (samples["origin_month"] == "2024-03")
            & (samples["source_entity_id"] == "SYN-E0001")
            & (samples["target_entity_id"] == "SYN-E0002")
        ]
        self.assertEqual(len(positive), 1)
        self.assertEqual(int(positive.iloc[0]["label"]), 1)
        self.assertTrue(set(demo.FEATURE_NAMES).issubset(samples.columns))

    def test_features_are_calculated_from_historical_snapshot(self):
        graph = nx.Graph()
        graph.add_edges_from([
            ("SYN-E0001", "SYN-E0003"),
            ("SYN-E0002", "SYN-E0003"),
            ("SYN-E0001", "SYN-E0004"),
        ])
        seen = {
            node: datetime(2024, 1, day)
            for node, day in [
                ("SYN-E0001", 1), ("SYN-E0002", 2),
                ("SYN-E0003", 3), ("SYN-E0004", 4),
            ]
        }
        features = demo._features_for_pair(
            graph, seen, ("SYN-E0001", "SYN-E0002"), datetime(2024, 2, 1)
        )
        self.assertEqual(features["common_neighbor_count"], 1.0)
        self.assertGreater(features["jaccard"], 0.0)
        self.assertGreater(features["adamic_adar"], 0.0)
        self.assertGreaterEqual(features["endpoint_recency_days"], 0.0)


class TrainingAndPersistenceTests(unittest.TestCase):
    @staticmethod
    def controlled_samples() -> dict[str, pd.DataFrame]:
        frames = {}
        for name, count, start in [
            ("train", 1000, "2024-03"),
            ("validation", 200, "2025-02"),
            ("test", 200, "2025-07"),
        ]:
            rows = []
            for index in range(count):
                label = index % 2
                rows.append({
                    "origin_month": start,
                    "prediction_period": "2024-04",
                    "source_entity_id": f"SYN-E{index + 1:04d}",
                    "target_entity_id": f"SYN-E{index + 2:04d}",
                    "common_neighbor_count": float(label * 2 + index % 3),
                    "jaccard": float(label * 0.5 + (index % 5) / 10),
                    "adamic_adar": float(label * 1.2 + index % 4),
                    "preferential_attachment": float(index % 7),
                    "degree_min": float(index % 5),
                    "degree_max": float(index % 11),
                    "endpoint_recency_days": float(index % 17),
                    "label": label,
                })
            frames[name] = pd.DataFrame(rows)
        return frames

    def test_training_and_inference_are_reproducible(self):
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        train = self.controlled_samples()["train"]
        models = []
        for _ in range(2):
            model = Pipeline([
                ("scaler", StandardScaler()),
                ("classifier", LogisticRegression(random_state=demo.RANDOM_SEED, max_iter=1000)),
            ])
            model.fit(train[demo.FEATURE_NAMES], train["label"])
            models.append(model.predict_proba(train[demo.FEATURE_NAMES])[:, 1])
        self.assertEqual(models[0].tolist(), models[1].tolist())

    def test_insufficient_data_stops_before_model_or_artifact_creation(self):
        splits = self.controlled_samples()
        splits["train"].loc[:, "label"] = 0
        with tempfile.TemporaryDirectory() as directory:
            all_samples = pd.concat(splits.values(), ignore_index=True)
            with (
                patch.object(demo, "build_temporal_samples", return_value=all_samples),
                patch.object(demo, "chronological_split", return_value=splits),
            ):
                with self.assertRaises(demo.InsufficientDataError):
                    demo.train_and_persist(
                        [], {"dataset_version": demo.DATASET_VERSION},
                        runs_dir=Path(directory),
                    )
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_thresholding_and_evaluation_metrics_are_computed(self):
        y_true = [0, 1, 0, 1]
        scores = [0.1, 0.9, 0.2, 0.8]
        threshold = demo._select_threshold(y_true, scores)
        metrics = demo._classification_metrics(y_true, scores, threshold)
        self.assertEqual(metrics["positive_prevalence"], 0.5)
        for key in ("accuracy", "precision", "recall", "f1", "roc_auc", "average_precision"):
            self.assertGreaterEqual(metrics[key], 0.0)
            self.assertLessEqual(metrics[key], 1.0)

    def test_prediction_artifact_contains_required_fields(self):
        frames = self.controlled_samples()
        all_samples = pd.concat(frames.values(), ignore_index=True)
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(demo, "build_temporal_samples", return_value=all_samples),
                patch.object(demo, "chronological_split", return_value=frames),
            ):
                result = demo.train_and_persist(
                    [], {"dataset_version": demo.DATASET_VERSION},
                    runs_dir=Path(directory),
                )
            predictions = pd.read_csv(Path(result["run_dir"]) / "predictions.csv")
            required = {
                "source_entity_id", "target_entity_id", "model_score",
                "model_version", "dataset_version", "prediction_period",
                "status", *demo.FEATURE_NAMES,
            }
            self.assertTrue(required.issubset(predictions.columns))
            self.assertTrue(predictions["status"].eq("ML_SUGGESTED_UNCONFIRMED").all())
            self.assertTrue(predictions["model_score"].is_monotonic_decreasing)

    def test_metadata_evaluation_prediction_schema_and_artifact_isolation(self):
        self.assertNotEqual(
            demo.DATASET_DIR,
            demo.PROJECT_ROOT / "data" / "raw",
        )
        self.assertNotEqual(
            demo.RUNS_DIR,
            demo.PROJECT_ROOT / "data" / "processed",
        )
        self.assertEqual(demo.PREDICTION_STATUS, "ML_SUGGESTED_UNCONFIRMED")
        self.assertIn("controlled synthetic ML demonstration", demo.LIMITATION)
        counts = demo.split_counts(self.controlled_samples())
        self.assertEqual(counts["train"]["positive"], 500)
        self.assertEqual(counts["validation"]["negative"], 100)

    def test_model_training_persistence_metadata_and_prediction_schema(self):
        frames = self.controlled_samples()
        all_samples = pd.concat(frames.values(), ignore_index=True)
        dataset_metadata = {"dataset_version": demo.DATASET_VERSION}
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(demo, "build_temporal_samples", return_value=all_samples),
                patch.object(demo, "chronological_split", return_value=frames),
            ):
                result = demo.train_and_persist(
                    [], dataset_metadata, runs_dir=Path(directory)
                )
            run_dir = Path(result["run_dir"])
            self.assertTrue((run_dir / "model.joblib").is_file())
            self.assertTrue((run_dir / "metadata.json").is_file())
            self.assertTrue((run_dir / "evaluation.json").is_file())
            self.assertTrue((run_dir / "predictions.csv").is_file())
            metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
            evaluation = json.loads((run_dir / "evaluation.json").read_text(encoding="utf-8"))
            predictions = pd.read_csv(run_dir / "predictions.csv")
            self.assertEqual(metadata["model_version"], demo.MODEL_VERSION)
            self.assertEqual(metadata["random_seed"], 26189)
            self.assertEqual(metadata["limitation"], demo.LIMITATION)
            self.assertIn("test", evaluation)
            self.assertIn("model_score", predictions)
            self.assertTrue(predictions["status"].eq(demo.PREDICTION_STATUS).all())
            self.assertTrue(predictions["source_entity_id"].str.startswith("SYN-").all())
            self.assertTrue(predictions["target_entity_id"].str.startswith("SYN-").all())
            self.assertFalse(any(
                (Path(directory) / production).exists()
                for production in ["graph.json", "relationships.csv", "risk_scores.csv"]
            ))

    def test_run_collision_is_refused(self):
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2025, 1, 1, tzinfo=tz)

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(demo, "datetime", FixedDateTime),
                patch.object(demo.uuid, "uuid4", return_value=type(
                    "FixedUUID", (), {"hex": "1234567890abcdef"}
                )()),
            ):
                demo._new_run_dir(Path(directory))
                with self.assertRaises(FileExistsError):
                    demo._new_run_dir(Path(directory))
