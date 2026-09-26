"""Controlled synthetic temporal link-prediction experiment.

This module does not read CIPHER investigative datasets or write CIPHER
analytical artifacts. Dataset generation and model training are explicit CLI
operations; importing the module has no filesystem side effects.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import logging
import math
import random
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from itertools import combinations
from pathlib import Path
from typing import Iterable

import networkx as nx
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = PROJECT_ROOT / "data" / "ml_experiment" / "datasets" / "synthetic-network-v1"
EVENTS_PATH = DATASET_DIR / "events.csv"
DATASET_METADATA_PATH = DATASET_DIR / "dataset_metadata.json"
RUNS_DIR = PROJECT_ROOT / "models" / "ml_experiment" / "runs"

DATASET_VERSION = "synthetic-network-v1"
MODEL_VERSION = "temporal-logistic-regression-v1"
RANDOM_SEED = 26189
ENTITY_COUNT = 180
GROUP_COUNT = 12
MONTH_COUNT = 24
EVENTS_PER_MONTH = 260
FEATURE_NAMES = [
    "common_neighbor_count",
    "jaccard",
    "adamic_adar",
    "preferential_attachment",
    "degree_min",
    "degree_max",
    "endpoint_recency_days",
]
LIMITATION = (
    "This is a controlled synthetic ML demonstration. Performance on this "
    "synthetic dataset does not establish real-world predictive validity."
)
PREDICTION_STATUS = "ML_SUGGESTED_UNCONFIRMED"
LOG = logging.getLogger(__name__)


class InsufficientDataError(ValueError):
    """Raised when chronological splits cannot support honest evaluation."""


def _month_start(index: int) -> date:
    if index < 1 or index > MONTH_COUNT:
        raise ValueError(f"Month index must be between 1 and {MONTH_COUNT}")
    return date(2024 + (index - 1) // 12, (index - 1) % 12 + 1, 1)


def _next_month(value: date) -> date:
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


def _month_string(value: date) -> str:
    return value.strftime("%Y-%m")


def _entity_pair(source: str, target: str) -> tuple[str, str]:
    return tuple(sorted((source, target)))


def _all_pairs(entity_ids: list[str]) -> list[tuple[str, str]]:
    return [
        (entity_ids[left], entity_ids[right])
        for left in range(len(entity_ids))
        for right in range(left + 1, len(entity_ids))
    ]


def _two_hop_pairs(graph: nx.Graph) -> set[tuple[str, str]]:
    return set(_two_hop_pair_counts(graph))


def _two_hop_pair_counts(graph: nx.Graph) -> dict[tuple[str, str], int]:
    common_counts: Counter[tuple[str, str]] = Counter()
    for node in graph:
        for left, right in combinations(sorted(graph.neighbors(node)), 2):
            if not graph.has_edge(left, right):
                common_counts[_entity_pair(str(left), str(right))] += 1
    return dict(common_counts)


def generate_events(seed: int = RANDOM_SEED) -> list[dict[str, str]]:
    """Generate a reproducible, controlled network event dataset in memory."""
    rng = random.Random(seed)
    entity_ids = [f"SYN-E{index:04d}" for index in range(1, ENTITY_COUNT + 1)]
    hidden_groups = {
        entity_id: (index - 1) % GROUP_COUNT
        for index, entity_id in enumerate(entity_ids, start=1)
    }
    all_pairs = _all_pairs(entity_ids)
    latent_weights = [
        1.7 if hidden_groups[left] == hidden_groups[right] else 1.0
        for left, right in all_pairs
    ]
    latent_cumulative = []
    cumulative_total = 0.0
    for weight in latent_weights:
        cumulative_total += weight
        latent_cumulative.append(cumulative_total)
    graph = nx.Graph()
    graph.add_nodes_from(entity_ids)
    events: list[dict[str, str]] = []
    event_number = 1

    for month_index in range(1, MONTH_COUNT + 1):
        month = _month_start(month_index)
        days_in_month = (_next_month(month) - month).days
        open_pair_counts = _two_hop_pair_counts(graph)
        closure_pairs = sorted(open_pair_counts)

        for _ in range(EVENTS_PER_MONTH):
            draw = rng.random()
            if draw < 0.45 and closure_pairs:
                index = rng.randrange(len(closure_pairs))
                pair = closure_pairs[index]
                closure_pairs[index] = closure_pairs[-1]
                closure_pairs.pop()
            elif draw < 0.70:
                index = bisect.bisect_left(
                    latent_cumulative,
                    rng.random() * latent_cumulative[-1],
                )
                pair = all_pairs[min(index, len(all_pairs) - 1)]
            else:
                pair = rng.choice(all_pairs)

            day = rng.randrange(days_in_month)
            second = rng.randrange(24 * 60 * 60)
            event_time = datetime.combine(month + timedelta(days=day), time()) + timedelta(
                seconds=second
            )
            events.append({
                "event_id": f"SYN-EVENT-{event_number:07d}",
                "source_entity_id": pair[0],
                "target_entity_id": pair[1],
                "timestamp": event_time.isoformat(timespec="seconds"),
                "event_type": "synthetic_interaction",
            })
            event_number += 1
            graph.add_edge(*pair)

    return events


def write_dataset_once(
    dataset_dir: Path = DATASET_DIR,
    seed: int = RANDOM_SEED,
) -> dict:
    """Persist the single versioned dataset; refuse to overwrite existing data."""
    dataset_dir = Path(dataset_dir)
    events_path = dataset_dir / "events.csv"
    metadata_path = dataset_dir / "dataset_metadata.json"
    if events_path.exists() or metadata_path.exists():
        raise FileExistsError(
            f"Synthetic dataset already exists in {dataset_dir}; refusing to overwrite"
        )

    events = generate_events(seed=seed)
    dataset_dir.mkdir(parents=True, exist_ok=False)
    with events_path.open("x", encoding="utf-8", newline="") as event_file:
        writer = csv.DictWriter(
            event_file,
            fieldnames=[
                "event_id", "source_entity_id", "target_entity_id",
                "timestamp", "event_type",
            ],
        )
        writer.writeheader()
        writer.writerows(events)

    metadata = {
        "dataset_version": DATASET_VERSION,
        "random_seed": seed,
        "entity_count": ENTITY_COUNT,
        "event_count": len(events),
        "time_start": min(event["timestamp"] for event in events),
        "time_end": max(event["timestamp"] for event in events),
        "events_per_month": EVENTS_PER_MONTH,
        "month_count": MONTH_COUNT,
        "schema": [
            "event_id", "source_entity_id", "target_entity_id",
            "timestamp", "event_type",
        ],
        "synthetic_only": True,
        "limitation": LIMITATION,
    }
    with metadata_path.open("x", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2)
    return metadata


def load_events(path: Path = EVENTS_PATH) -> list[dict[str, str]]:
    """Load and validate synthetic events from the experiment namespace."""
    with Path(path).open(encoding="utf-8", newline="") as event_file:
        events = list(csv.DictReader(event_file))
    required = {
        "event_id", "source_entity_id", "target_entity_id", "timestamp", "event_type",
    }
    if not events or not required.issubset(events[0]):
        raise ValueError("Synthetic event file is empty or has an invalid schema")
    for event in events:
        if not event["source_entity_id"].startswith("SYN-"):
            raise ValueError("Synthetic source ID must use the SYN- namespace")
        if not event["target_entity_id"].startswith("SYN-"):
            raise ValueError("Synthetic target ID must use the SYN- namespace")
        if event["source_entity_id"] == event["target_entity_id"]:
            raise ValueError("Self-interaction is not a valid event")
        datetime.fromisoformat(event["timestamp"])
    return events


def _parse_events(events: Iterable[dict[str, str]]) -> list[tuple[datetime, str, str]]:
    parsed = []
    for event in events:
        timestamp = datetime.fromisoformat(event["timestamp"])
        source, target = _entity_pair(
            event["source_entity_id"], event["target_entity_id"]
        )
        parsed.append((timestamp, source, target))
    return sorted(parsed)


def _features_for_pair(
    graph: nx.Graph,
    last_seen: dict[str, datetime],
    pair: tuple[str, str],
    cutoff: datetime,
) -> dict[str, float]:
    left, right = pair
    left_neighbors = set(graph.neighbors(left))
    right_neighbors = set(graph.neighbors(right))
    common = left_neighbors & right_neighbors
    union_size = len(left_neighbors | right_neighbors)
    adamic_adar = sum(
        1.0 / max(1.0, math.log(graph.degree(node)))
        for node in common
        if graph.degree(node) > 1
    )
    recent_endpoint_seen = max(
        (last_seen.get(left), last_seen.get(right)),
        key=lambda value: value or datetime.min,
    )
    recency_days = (
        max(0.0, (cutoff - recent_endpoint_seen).total_seconds() / 86400)
        if recent_endpoint_seen is not None
        else 36500.0
    )
    return {
        "common_neighbor_count": float(len(common)),
        "jaccard": float(len(common) / union_size) if union_size else 0.0,
        "adamic_adar": float(adamic_adar),
        "preferential_attachment": float(len(left_neighbors) * len(right_neighbors)),
        "degree_min": float(min(len(left_neighbors), len(right_neighbors))),
        "degree_max": float(max(len(left_neighbors), len(right_neighbors))),
        "endpoint_recency_days": float(recency_days),
    }


def build_temporal_samples(events: list[dict[str, str]]) -> pd.DataFrame:
    """Build cutoff-only features and next-month labels for pair snapshots."""
    parsed = _parse_events(events)
    monthly_events: dict[str, list[tuple[datetime, str, str]]] = defaultdict(list)
    for timestamp, source, target in parsed:
        monthly_events[timestamp.strftime("%Y-%m")].append((timestamp, source, target))

    samples: list[dict] = []
    graph = nx.Graph()
    last_seen: dict[str, datetime] = {}
    for month_index in range(1, MONTH_COUNT):
        cutoff_month = _month_start(month_index)
        prediction_month = _next_month(cutoff_month)
        cutoff = datetime.combine(prediction_month, time())
        for month_event in monthly_events.get(_month_string(cutoff_month), []):
            timestamp, source, target = month_event
            graph.add_edge(source, target)
            last_seen[source] = max(last_seen.get(source, datetime.min), timestamp)
            last_seen[target] = max(last_seen.get(target, datetime.min), timestamp)

        if month_index < 3 or month_index not in set(
            list(range(3, 13)) + list(range(14, 18)) + list(range(19, 24))
        ):
            continue

        horizon_events = monthly_events.get(_month_string(prediction_month), [])
        positive_pairs = {
            _entity_pair(source, target)
            for _, source, target in horizon_events
        }
        for pair in sorted(_two_hop_pairs(graph)):
            if graph.has_edge(*pair):
                continue
            feature_values = _features_for_pair(graph, last_seen, pair, cutoff)
            samples.append({
                "origin_month": _month_string(cutoff_month),
                "prediction_period": _month_string(prediction_month),
                "source_entity_id": pair[0],
                "target_entity_id": pair[1],
                **feature_values,
                "label": int(pair in positive_pairs),
            })

    return pd.DataFrame(samples, columns=[
        "origin_month", "prediction_period", "source_entity_id",
        "target_entity_id", *FEATURE_NAMES, "label",
    ])


def chronological_split(samples: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split pair snapshots by the approved chronological origin periods."""
    origins = pd.to_datetime(samples["origin_month"] + "-01")
    train = samples[(origins >= "2024-03-01") & (origins <= "2024-12-01")].copy()
    validation = samples[
        (origins >= "2025-02-01") & (origins <= "2025-05-01")
    ].copy()
    test = samples[(origins >= "2025-07-01") & (origins <= "2025-11-01")].copy()
    return {"train": train, "validation": validation, "test": test}


def split_counts(splits: dict[str, pd.DataFrame]) -> dict[str, dict[str, int]]:
    counts = {}
    for name, frame in splits.items():
        labels = frame["label"].value_counts().to_dict() if "label" in frame else {}
        counts[name] = {
            "samples": int(len(frame)),
            "positive": int(labels.get(1, 0)),
            "negative": int(labels.get(0, 0)),
        }
    return counts


def check_sufficiency(splits: dict[str, pd.DataFrame]) -> dict[str, dict[str, int]]:
    counts = split_counts(splits)
    requirements = {"train": 500, "validation": 100, "test": 100}
    failures = []
    for split, minimum in requirements.items():
        entry = counts[split]
        if entry["positive"] < minimum or entry["negative"] < minimum:
            failures.append(
                f"{split}: positives={entry['positive']} negatives={entry['negative']} "
                f"(minimum {minimum} each)"
            )
    if failures:
        raise InsufficientDataError(
            "Insufficient temporal examples; no model was trained: " + "; ".join(failures)
        )
    return counts


def _classification_metrics(y_true, scores, threshold: float) -> dict[str, float | int]:
    from sklearn.metrics import (
        accuracy_score,
        average_precision_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    predictions = [int(score >= threshold) for score in scores]
    return {
        "positive_prevalence": float(sum(y_true) / len(y_true)),
        "accuracy": float(accuracy_score(y_true, predictions)),
        "precision": float(precision_score(y_true, predictions, zero_division=0)),
        "recall": float(recall_score(y_true, predictions, zero_division=0)),
        "f1": float(f1_score(y_true, predictions, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, scores)),
        "average_precision": float(average_precision_score(y_true, scores)),
        "threshold": float(threshold),
        "samples": int(len(y_true)),
    }


def _select_threshold(y_true, scores) -> float:
    from sklearn.metrics import precision_recall_curve

    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    if not len(thresholds):
        return 0.5
    f1_values = [
        (2 * p * r / (p + r)) if p + r else 0.0
        for p, r in zip(precision[:-1], recall[:-1])
    ]
    best_index = max(range(len(thresholds)), key=lambda index: (f1_values[index], thresholds[index]))
    return float(thresholds[best_index])


def _adamic_adar_scores(frame: pd.DataFrame) -> list[float]:
    # Fixed monotonic scaling keeps validation and test thresholds comparable.
    values = frame["adamic_adar"].astype(float)
    return (values / (1.0 + values)).tolist()


def _new_run_dir(runs_dir: Path = RUNS_DIR) -> tuple[Path, str]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"
    run_dir = Path(runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir, run_id


def train_and_persist(
    events: list[dict[str, str]],
    dataset_metadata: dict,
    runs_dir: Path = RUNS_DIR,
) -> dict:
    """Train and persist one model after chronological sufficiency validation."""
    samples = build_temporal_samples(events)
    splits = chronological_split(samples)
    counts = check_sufficiency(splits)

    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    train = splits["train"]
    validation = splits["validation"]
    test = splits["test"]
    model = Pipeline([
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(
            random_state=RANDOM_SEED,
            max_iter=1000,
            solver="lbfgs",
        )),
    ])
    model.fit(train[FEATURE_NAMES], train["label"])

    validation_scores = model.predict_proba(validation[FEATURE_NAMES])[:, 1]
    model_threshold = _select_threshold(validation["label"].tolist(), validation_scores)
    baseline_validation = _adamic_adar_scores(validation)
    baseline_threshold = _select_threshold(
        validation["label"].tolist(), baseline_validation
    )

    # The test split is first scored only after the model and both thresholds
    # are fixed using training and validation data.
    test_scores = model.predict_proba(test[FEATURE_NAMES])[:, 1]
    baseline_test = _adamic_adar_scores(test)
    evaluation = {
        "validation": {
            "model": _classification_metrics(
                validation["label"].tolist(), validation_scores, model_threshold
            ),
            "adamic_adar_baseline": _classification_metrics(
                validation["label"].tolist(), baseline_validation, baseline_threshold
            ),
        },
        "test": {
            "model": _classification_metrics(
                test["label"].tolist(), test_scores, model_threshold
            ),
            "adamic_adar_baseline": _classification_metrics(
                test["label"].tolist(), baseline_test, baseline_threshold
            ),
        },
    }

    run_dir, run_id = _new_run_dir(Path(runs_dir))
    import joblib

    model_path = run_dir / "model.joblib"
    joblib.dump(model, model_path)
    prediction_frame = test[
        ["prediction_period", "source_entity_id", "target_entity_id", *FEATURE_NAMES]
    ].copy()
    prediction_frame["model_score"] = test_scores
    prediction_frame["model_version"] = MODEL_VERSION
    prediction_frame["dataset_version"] = dataset_metadata["dataset_version"]
    prediction_frame["status"] = PREDICTION_STATUS
    prediction_frame = prediction_frame.sort_values(
        "model_score", ascending=False, kind="stable"
    )
    prediction_frame.to_csv(run_dir / "predictions.csv", index=False)

    metadata = {
        "run_id": run_id,
        "model_type": "StandardScaler + LogisticRegression",
        "model_version": MODEL_VERSION,
        "dataset_version": dataset_metadata["dataset_version"],
        "random_seed": RANDOM_SEED,
        "feature_names": FEATURE_NAMES,
        "training_period": {
            "feature_origins": ["2024-03", "2024-12"],
            "label_periods": ["2024-04", "2025-01"],
        },
        "validation_period": {
            "feature_origins": ["2025-02", "2025-05"],
            "label_periods": ["2025-03", "2025-06"],
        },
        "test_period": {
            "feature_origins": ["2025-07", "2025-11"],
            "label_periods": ["2025-08", "2025-12"],
        },
        "split_counts": counts,
        "evaluation_metrics": evaluation,
        "training_timestamp": datetime.now(timezone.utc).isoformat(),
        "source_artifacts": [str(DATASET_METADATA_PATH), str(EVENTS_PATH)],
        "synthetic_only": True,
        "observed_graph_integration": False,
        "limitation": LIMITATION,
    }
    with (run_dir / "metadata.json").open("x", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2)
    with (run_dir / "evaluation.json").open("x", encoding="utf-8") as evaluation_file:
        json.dump(evaluation, evaluation_file, indent=2)
    return {
        "run_dir": str(run_dir),
        "metadata": metadata,
        "evaluation": evaluation,
        "samples": counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--generate-dataset", action="store_true")
    action.add_argument("--train", action="store_true")
    args = parser.parse_args()

    if args.generate_dataset:
        metadata = write_dataset_once()
        print(json.dumps(metadata, indent=2))
        return

    dataset_metadata = json.loads(DATASET_METADATA_PATH.read_text(encoding="utf-8"))
    events = load_events()
    result = train_and_persist(events, dataset_metadata)
    print(json.dumps({
        "run_dir": result["run_dir"],
        "split_counts": result["samples"],
        "evaluation": result["evaluation"],
        "limitation": LIMITATION,
    }, indent=2))


if __name__ == "__main__":
    main()
