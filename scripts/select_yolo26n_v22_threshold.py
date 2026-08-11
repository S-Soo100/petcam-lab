"""Select and freeze a development-only YOLO26n v2.2 confidence threshold."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class ThresholdSelectionError(ValueError):
    pass


@dataclass(frozen=True)
class ThresholdMetric:
    threshold: float
    precision: float
    recall: float


def _valid_probability(value: float) -> bool:
    return not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


def select_threshold(
    rows: Iterable[ThresholdMetric], *, precision_floor: float = 0.60
) -> ThresholdMetric:
    if not _valid_probability(precision_floor):
        raise ThresholdSelectionError("precision floor must be in [0, 1]")
    frozen = tuple(rows)
    for row in frozen:
        if not all(
            _valid_probability(value)
            for value in (row.threshold, row.precision, row.recall)
        ):
            raise ThresholdSelectionError("threshold metrics must be finite probabilities")
    eligible = [row for row in frozen if row.precision >= precision_floor]
    if not eligible:
        raise ThresholdSelectionError("precision floor is unreachable")
    return max(eligible, key=lambda row: (row.recall, row.precision, row.threshold))


def write_threshold_freeze(
    *,
    selected: ThresholdMetric,
    precision_floor: float,
    prediction_ledger_sha256: str,
    output_path: Path,
) -> None:
    if not (
        len(prediction_ledger_sha256) == 64
        and prediction_ledger_sha256 == prediction_ledger_sha256.lower()
        and all(character in "0123456789abcdef" for character in prediction_ledger_sha256)
    ):
        raise ThresholdSelectionError("prediction ledger SHA-256 is invalid")
    if output_path.exists():
        raise FileExistsError(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            {
                "schema": "yolo26n-v22-threshold-freeze-v1",
                "status": "V22_THRESHOLD_FROZEN_DEVELOPMENT_ONLY",
                "evaluation_tier": "development",
                "future_holdout_required": True,
                "threshold": selected.threshold,
                "precision": selected.precision,
                "recall": selected.recall,
                "precision_floor": precision_floor,
                "prediction_ledger_sha256": prediction_ledger_sha256,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        output_path.unlink(missing_ok=True)
        raise
