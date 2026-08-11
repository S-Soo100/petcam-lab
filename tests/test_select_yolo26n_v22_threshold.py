import json
from pathlib import Path

import pytest

from scripts.select_yolo26n_v22_threshold import (
    ThresholdMetric,
    ThresholdSelectionError,
    select_threshold,
    write_threshold_freeze,
)


def test_select_threshold_maximizes_recall_above_precision_floor():
    rows = [
        ThresholdMetric(0.10, precision=0.55, recall=0.90),
        ThresholdMetric(0.20, precision=0.61, recall=0.82),
        ThresholdMetric(0.30, precision=0.70, recall=0.75),
    ]

    assert select_threshold(rows, precision_floor=0.60).threshold == 0.20


def test_select_threshold_fails_when_precision_floor_is_unreachable():
    with pytest.raises(ThresholdSelectionError, match="unreachable"):
        select_threshold(
            [ThresholdMetric(0.1, precision=0.59, recall=0.99)],
            precision_floor=0.60,
        )


def test_threshold_freeze_is_private_and_no_overwrite(tmp_path: Path):
    output = tmp_path / "threshold-freeze.private.json"
    row = ThresholdMetric(0.2, precision=0.61, recall=0.82)

    write_threshold_freeze(
        selected=row,
        precision_floor=0.60,
        prediction_ledger_sha256="a" * 64,
        output_path=output,
    )

    saved = json.loads(output.read_text())
    assert saved["status"] == "V22_THRESHOLD_FROZEN_DEVELOPMENT_ONLY"
    assert saved["threshold"] == 0.2
    assert output.stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        write_threshold_freeze(
            selected=row,
            precision_floor=0.60,
            prediction_ledger_sha256="a" * 64,
            output_path=output,
        )
