from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


FROZEN = {
    "eligible_count": 172,
    "eligible_ordered_sha256": (
        "8e2bf4e73f8f033288d7632e25e2fbfd"
        "69d3de98c62dade2996bbe33686c96ba"
    ),
    "moving_count": 108,
    "static_only_count": 32,
    "excluded_count": 32,
    "episode_count": 39,
    "provenance_contract_count": 1,
}
ALLOWED_LABELS = {"moving", "static_only", "excluded"}
NUMERIC_FIELDS = {
    "decoded_frame_count",
    "global_series_length",
    "roi_series_length",
    "roi_mean",
    "observed_sec",
    "peak_autocorr",
}
REQUIRED_FIELDS = {
    "sample_key",
    "episode_key",
    "camera_group",
    "camera_night",
    "label",
    "level0_status",
    "level1_status",
    *NUMERIC_FIELDS,
}
PRIMARY_FEATURE = "roi_mean"
SECONDARY_FEATURES = ("observed_sec", "peak_autocorr", "decoded_frame_count")
BOOTSTRAP_ITERATIONS = 10_000
BOOTSTRAP_SEED = 20_260_727


def validate_snapshot(snapshot: dict, expected: dict | None = None) -> None:
    contract = snapshot.get("contract")
    records = snapshot.get("records")
    if not isinstance(contract, dict) or not isinstance(records, list):
        raise ValueError("snapshot requires contract and records")

    wanted = FROZEN if expected is None else expected
    for key, value in wanted.items():
        if contract.get(key) != value:
            raise ValueError(f"{key}: expected {value}, got {contract.get(key)}")
    if len(records) != contract["eligible_count"]:
        raise ValueError("record count does not match eligible_count")

    sample_keys: set[str] = set()
    episode_keys: set[str] = set()
    label_counts: Counter[str] = Counter()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"record {index} must be an object")
        missing = REQUIRED_FIELDS - record.keys()
        if missing:
            raise ValueError(f"record {index} missing fields: {sorted(missing)}")
        if record["label"] not in ALLOWED_LABELS:
            raise ValueError(f"record {index} invalid label")
        sample_key = record["sample_key"]
        if not isinstance(sample_key, str) or not sample_key:
            raise ValueError(f"record {index} invalid sample_key")
        if sample_key in sample_keys:
            raise ValueError(f"duplicate sample_key: {sample_key}")
        sample_keys.add(sample_key)
        for field in ("episode_key", "camera_group", "camera_night"):
            if not isinstance(record[field], str) or not record[field]:
                raise ValueError(f"record {index} invalid {field}")
        episode_keys.add(record["episode_key"])
        label_counts[record["label"]] += 1
        for field in NUMERIC_FIELDS:
            value = record[field]
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError(f"record {index} {field} must be finite numeric or null")

    if len(episode_keys) != contract["episode_count"]:
        raise ValueError("episode_count does not match records")
    for label in ALLOWED_LABELS:
        key = f"{label}_count"
        if label_counts[label] != contract[key]:
            raise ValueError(f"{key} does not match records")


def auc_higher(records: list[dict], feature: str) -> float:
    positive = [
        float(record[feature])
        for record in records
        if record["label"] == "moving" and record.get(feature) is not None
    ]
    negative = [
        float(record[feature])
        for record in records
        if record["label"] == "static_only" and record.get(feature) is not None
    ]
    if not positive or not negative:
        raise ValueError("AUROC requires both classes")
    wins = sum(
        1.0 if positive_value > negative_value
        else 0.5 if positive_value == negative_value
        else 0.0
        for positive_value in positive
        for negative_value in negative
    )
    return wins / (len(positive) * len(negative))


def _percentile(values: list[float], proportion: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def cluster_bootstrap(
    records: list[dict],
    feature: str,
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    by_episode: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if record["label"] in {"moving", "static_only"}:
            by_episode[record["episode_key"]].append(record)
    episode_keys = sorted(by_episode)
    if not episode_keys:
        raise ValueError("bootstrap requires episodes")

    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(iterations):
        sampled_keys = rng.choices(episode_keys, k=len(episode_keys))
        sampled_records = [
            record
            for episode_key in sampled_keys
            for record in by_episode[episode_key]
        ]
        labels = {record["label"] for record in sampled_records if record.get(feature) is not None}
        if {"moving", "static_only"} <= labels:
            estimates.append(auc_higher(sampled_records, feature))

    if not estimates:
        raise ValueError("bootstrap produced no valid iterations")
    return {
        "seed": seed,
        "iterations": iterations,
        "valid_iterations": len(estimates),
        "valid_fraction": len(estimates) / iterations,
        "sampled_episode_count": len(episode_keys),
        "ci_low": _percentile(estimates, 0.025),
        "ci_high": _percentile(estimates, 0.975),
    }


def _distribution(records: list[dict], feature: str) -> dict:
    values = [
        float(record[feature])
        for record in records
        if record.get(feature) is not None
    ]
    if not values:
        return {
            "non_null": 0,
            "median": None,
            "q1": None,
            "q3": None,
            "iqr": None,
        }
    q1 = _percentile(values, 0.25)
    q3 = _percentile(values, 0.75)
    return {
        "non_null": len(values),
        "median": statistics.median(values),
        "q1": q1,
        "q3": q3,
        "iqr": q3 - q1,
    }


def _hodges_lehmann(records: list[dict], feature: str) -> float | None:
    positive = [
        float(record[feature])
        for record in records
        if record["label"] == "moving" and record.get(feature) is not None
    ]
    negative = [
        float(record[feature])
        for record in records
        if record["label"] == "static_only" and record.get(feature) is not None
    ]
    if not positive or not negative:
        return None
    return statistics.median(
        positive_value - negative_value
        for positive_value in positive
        for negative_value in negative
    )


def _camera_auc(records: list[dict], feature: str) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for camera in sorted({record["camera_group"] for record in records}):
        camera_records = [record for record in records if record["camera_group"] == camera]
        labels = {
            record["label"]
            for record in camera_records
            if record.get(feature) is not None
        }
        result[camera] = (
            auc_higher(camera_records, feature)
            if {"moving", "static_only"} <= labels
            else None
        )
    return result


def decide(summary: dict) -> str:
    primary = summary["primary"]
    coverage = primary["coverage"]
    if coverage < 0.80 or primary["ci_high"] <= 0.50:
        return "PE_MOTION_SIGNAL_REJECTED"
    camera_values = list(primary["camera_auc"].values())
    if (
        coverage >= 0.95
        and primary["ci_low"] > 0.50
        and primary["valid_fraction"] >= 0.95
        and len(camera_values) == 2
        and all(value is not None and value > 0.50 for value in camera_values)
    ):
        return "PE_MOTION_SIGNAL_DESCRIPTIVE_SUPPORTED"
    return "PE_MOTION_SIGNAL_INCONCLUSIVE"


def summarize(
    snapshot: dict,
    expected: dict | None = None,
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    validate_snapshot(snapshot, expected=expected)
    records = snapshot["records"]
    discrimination = [
        record
        for record in records
        if record["label"] in {"moving", "static_only"}
    ]
    primary_non_null = [
        record for record in discrimination if record[PRIMARY_FEATURE] is not None
    ]
    bootstrap = cluster_bootstrap(
        records,
        PRIMARY_FEATURE,
        iterations=iterations,
        seed=seed,
    )
    camera_auc = _camera_auc(discrimination, PRIMARY_FEATURE)
    primary = {
        "feature": PRIMARY_FEATURE,
        "direction": "higher_is_moving",
        "non_null": len(primary_non_null),
        "denominator": len(discrimination),
        "coverage": len(primary_non_null) / len(discrimination),
        "auc": auc_higher(discrimination, PRIMARY_FEATURE),
        "ci_low": bootstrap["ci_low"],
        "ci_high": bootstrap["ci_high"],
        "bootstrap_seed": seed,
        "bootstrap_iterations": iterations,
        "valid_iterations": bootstrap["valid_iterations"],
        "valid_fraction": bootstrap["valid_fraction"],
        "episode_count": bootstrap["sampled_episode_count"],
        "camera_auc": camera_auc,
        "moving": _distribution(
            [record for record in discrimination if record["label"] == "moving"],
            PRIMARY_FEATURE,
        ),
        "static_only": _distribution(
            [
                record
                for record in discrimination
                if record["label"] == "static_only"
            ],
            PRIMARY_FEATURE,
        ),
        "hodges_lehmann_moving_minus_static": _hodges_lehmann(
            discrimination,
            PRIMARY_FEATURE,
        ),
    }
    camera_night = {
        camera_night_key: _distribution(
            [
                record
                for record in records
                if record["camera_night"] == camera_night_key
            ],
            PRIMARY_FEATURE,
        )
        for camera_night_key in sorted(
            {record["camera_night"] for record in records}
        )
    }
    summary = {
        "contract": snapshot["contract"],
        "analysis": {
            "kind": "retrospective_descriptive",
            "primary_feature": PRIMARY_FEATURE,
            "bootstrap_seed": seed,
            "bootstrap_iterations": iterations,
        },
        "technical": {
            "eligible_count": len(records),
            "level0_ok": sum(record["level0_status"] == "ok" for record in records),
            "level1_ok": sum(record["level1_status"] == "ok" for record in records),
            "episodes": len({record["episode_key"] for record in records}),
            "cameras": len({record["camera_group"] for record in records}),
            "camera_nights": len({record["camera_night"] for record in records}),
            "decoded_frame_count": _distribution(records, "decoded_frame_count"),
            "global_series_length": _distribution(records, "global_series_length"),
            "roi_series_length": _distribution(records, "roi_series_length"),
        },
        "labels": {
            label: sum(record["label"] == label for record in records)
            for label in sorted(ALLOWED_LABELS)
        },
        "primary": primary,
        "secondary": {
            feature: _distribution(records, feature)
            for feature in SECONDARY_FEATURES
        },
        "camera_night": camera_night,
    }
    summary["verdict"] = decide(summary)
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    snapshot: dict[str, Any] = json.loads(args.snapshot.read_text(encoding="utf-8"))
    summary = summarize(snapshot)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(summary["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
