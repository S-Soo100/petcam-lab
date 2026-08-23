"""Strict scoring and privacy contracts for the GME-negative audit."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
from uuid import UUID, uuid5

import pytest

from scripts.gme_negative_audit_sampling import (
    CHECKPOINT_SHA256,
    DETECTOR_IDENTITY,
    _canonical_json,
    build_private_manifest,
    select_calibration_batch,
)
from scripts.score_gme_negative_audit import (
    ScoreContractError,
    export_score_batch,
    score_audit,
    wilson_interval95,
)


_NAMESPACE = UUID("4e350645-cb35-45b1-b2bf-c674ff0ee281")
_OWNER_ID = str(uuid5(_NAMESPACE, "owner"))
_REVIEWER_ID = str(uuid5(_NAMESPACE, "reviewer"))
_BATCH_ID = str(uuid5(_NAMESPACE, "batch"))


def _uuid(label: str) -> str:
    return str(uuid5(_NAMESPACE, label))


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _candidate(index: int, stratum: str) -> dict[str, object]:
    control = stratum == "positive_control"
    return {
        "clip_id": _uuid(f"clip:{stratum}:{index}"),
        "stratum": stratum,
        "started_at": (
            datetime(2026, 8, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
        ).isoformat().replace("+00:00", "Z"),
        "duration_sec": 60.0,
        "camera_night_key": f"camera-night-{index % 6:02d}",
        "episode_key": f"episode-{stratum}-{index:03d}",
        "gme_run_id": _uuid("gme-run"),
        "detector_identity": DETECTOR_IDENTITY,
        "media_sha256": _digest(f"media:{stratum}:{index}"),
        "media_dhash": f"{0x1000000000000000 + index + (1000 if control else 0):016x}",
        "gme_detected": control,
        "human_gt_digest": _digest(f"gt:{index}") if control else None,
    }


@pytest.fixture(scope="module")
def manifest() -> dict[str, object]:
    selection = select_calibration_batch(
        [_candidate(index, "random_negative") for index in range(120)],
        [_candidate(index, "positive_control") for index in range(30)],
        protected_sha256=set(),
        protected_dhash64=set(),
        seed="gme-negative-audit-calibration-v1",
    )
    return build_private_manifest(
        selection,
        test_sheet_sha256=_digest("test-sheet"),
        cutoff="2026-08-01T00:00:00Z",
        checkpoint_sha256=CHECKPOINT_SHA256,
        protected_manifest_sha256=[_digest("training-manifest")],
    )


def _verdict_shape(verdict: str) -> tuple[float | None, dict[str, float] | None]:
    if verdict != "gecko_present":
        return None, None
    return 12.5, {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}


def _ledger(
    manifest: dict[str, object],
    *,
    negative_present: int = 6,
    negative_uncertain: int = 0,
    negative_media_error: int = 0,
    control_present: int = 29,
    control_uncertain: int = 0,
) -> dict[str, object]:
    items: list[dict[str, object]] = []
    submissions: list[dict[str, object]] = []
    negative_index = 0
    control_index = 0
    for raw_item in manifest["items"]:  # type: ignore[index]
        frozen = dict(raw_item)
        item_id = _uuid(f"item:{frozen['ordinal']}")
        if frozen["stratum"] == "random_negative":
            if negative_index < negative_present:
                verdict = "gecko_present"
            elif negative_index < negative_present + negative_uncertain:
                verdict = "uncertain"
            elif negative_index < negative_present + negative_uncertain + negative_media_error:
                verdict = "media_error"
            else:
                verdict = "gecko_absent"
            negative_index += 1
        else:
            if control_index < control_present:
                verdict = "gecko_present"
            elif control_index < control_present + control_uncertain:
                verdict = "uncertain"
            else:
                verdict = "gecko_absent"
            control_index += 1
        representative_sec, bbox = _verdict_shape(verdict)
        items.append(
            {
                "id": item_id,
                "batch_id": _BATCH_ID,
                **frozen,
                "assigned_reviewer_id": _OWNER_ID,
                "media_sha256_before": frozen["media_sha256"],
                "media_sha256_after": frozen["media_sha256"],
            }
        )
        submissions.append(
            {
                "id": _uuid(f"submission:{frozen['ordinal']}"),
                "item_id": item_id,
                "reviewer_id": _OWNER_ID,
                "verdict": verdict,
                "representative_sec": representative_sec,
                "bbox": bbox,
                "digest": _digest(f"submission:{frozen['ordinal']}"),
                "created_at": "2026-08-23T01:00:00Z",
            }
        )

    manifest_raw_sha256 = hashlib.sha256(_canonical_json(manifest) + b"\n").hexdigest()
    return {
        "schema_version": "gme-negative-audit-score-ledger-v1",
        "manifest_raw_sha256": manifest_raw_sha256,
        "batch": {
            "id": _BATCH_ID,
            "owner_id": _OWNER_ID,
            "schema_version": "gme-negative-audit-v1",
            "batch_kind": "calibration",
            "manifest_sha256": manifest["manifest_sha256"],
            "expected_negative_count": 120,
            "expected_control_count": 30,
            "expected_total_count": 150,
        },
        "items": items,
        "submissions": submissions,
        "corrections": [],
        "adjudications": [],
        "dataset_decisions": [],
    }


def test_score_separates_negative_and_control_and_requires_adjudication(
    manifest: dict[str, object],
) -> None:
    score = score_audit(manifest, _ledger(manifest))

    assert score.random_negative == 120
    assert score.negative_present == 6
    assert score.negative_valid == 120
    assert score.negative_pool_gecko_prevalence == pytest.approx(0.05)
    assert score.control_total == 30
    assert score.control_detected == 29
    assert score.control_detection_rate == pytest.approx(29 / 30)
    assert not hasattr(score, "recall")
    assert not hasattr(score, "false_negative_rate")


def test_uncertain_and_media_error_are_reported_but_excluded_from_denominator(
    manifest: dict[str, object],
) -> None:
    score = score_audit(
        manifest,
        _ledger(manifest, negative_present=6, negative_uncertain=8, negative_media_error=6),
    )

    assert score.negative_present == 6
    assert score.negative_absent == 100
    assert score.negative_valid == 106
    assert score.negative_uncertain == 8
    assert score.negative_media_error == 6
    assert score.negative_pool_gecko_prevalence == pytest.approx(6 / 106)


def test_control_detection_uses_all_frozen_controls_as_its_separate_denominator(
    manifest: dict[str, object],
) -> None:
    score = score_audit(
        manifest,
        _ledger(manifest, control_present=25, control_uncertain=2),
    )

    assert score.control_total == 30
    assert score.control_detected == 25
    assert score.control_uncertain == 2
    assert score.control_absent == 3
    assert score.control_detection_rate == pytest.approx(25 / 30)


def test_scorer_accepts_task1_control_with_false_pinned_gme_result() -> None:
    controls = [_candidate(index, "positive_control") for index in range(30)]
    for control in controls:
        control["gme_detected"] = False
    selection = select_calibration_batch(
        [_candidate(index, "random_negative") for index in range(120)],
        controls,
        protected_sha256=set(),
        protected_dhash64=set(),
        seed="gme-negative-audit-calibration-v1",
    )
    task1_manifest = build_private_manifest(
        selection,
        test_sheet_sha256=_digest("test-sheet"),
        cutoff="2026-08-01T00:00:00Z",
        checkpoint_sha256=CHECKPOINT_SHA256,
        protected_manifest_sha256=[],
    )

    score = score_audit(task1_manifest, _ledger(task1_manifest))

    assert score.control_total == 30
    assert score.control_detected == 29


def test_non_owner_non_absent_without_adjudication_fails_closed(
    manifest: dict[str, object],
) -> None:
    ledger = _ledger(manifest)
    first = ledger["submissions"][0]  # type: ignore[index]
    ledger["items"][0]["assigned_reviewer_id"] = _REVIEWER_ID  # type: ignore[index]
    first["reviewer_id"] = _REVIEWER_ID

    with pytest.raises(ScoreContractError, match="adjudication"):
        score_audit(manifest, ledger)


def test_owner_adjudication_overrides_latest_valid_correction(
    manifest: dict[str, object],
) -> None:
    ledger = _ledger(manifest)
    item = ledger["items"][0]  # type: ignore[index]
    submission = ledger["submissions"][0]  # type: ignore[index]
    item["assigned_reviewer_id"] = _REVIEWER_ID
    submission["reviewer_id"] = _REVIEWER_ID
    correction_digest = _digest("correction:1")
    ledger["corrections"] = [
        {
            "id": _uuid("correction:1"),
            "item_id": item["id"],
            "original_submission_id": submission["id"],
            "reviewer_id": _REVIEWER_ID,
            "verdict": "uncertain",
            "representative_sec": None,
            "bbox": None,
            "reason": "다시 보니 가림이 커.",
            "expected_submission_digest": submission["digest"],
            "digest": correction_digest,
            "created_at": "2026-08-23T01:01:00Z",
        }
    ]
    ledger["adjudications"] = [
        {
            "id": _uuid("adjudication:1"),
            "item_id": item["id"],
            "original_submission_id": submission["id"],
            "owner_id": _OWNER_ID,
            "final_verdict": "gecko_absent",
            "representative_sec": None,
            "bbox": None,
            "reason": "Owner 확인 결과 게코 없음.",
            "effective_submission_digest": correction_digest,
            "digest": _digest("adjudication:1"),
            "created_at": "2026-08-23T01:02:00Z",
        }
    ]

    score = score_audit(manifest, ledger)

    assert score.negative_present == 5
    assert score.negative_absent == 115


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda ledger: ledger.__setitem__("extra", True), "ledger.*exact"),
        (
            lambda ledger: ledger["items"].reverse(),  # type: ignore[union-attr]
            "order",
        ),
        (
            lambda ledger: ledger["items"][0].__setitem__("assigned_reviewer_id", _REVIEWER_ID),  # type: ignore[index]
            "assignment",
        ),
        (
            lambda ledger: ledger["items"][0].__setitem__("media_sha256_after", _digest("mutated")),  # type: ignore[index]
            "media.*mutat",
        ),
        (
            lambda ledger: ledger.__setitem__("manifest_raw_sha256", _digest("other manifest")),
            "manifest raw SHA",
        ),
    ],
)
def test_strict_manifest_ledger_order_assignment_and_media_pins_fail_closed(
    manifest: dict[str, object], mutation, message: str,
) -> None:
    ledger = _ledger(manifest)
    mutation(ledger)

    with pytest.raises(ScoreContractError, match=message):
        score_audit(manifest, ledger)


def test_correction_chain_and_digest_uniqueness_fail_closed(
    manifest: dict[str, object],
) -> None:
    ledger = _ledger(manifest)
    item = ledger["items"][0]  # type: ignore[index]
    submission = ledger["submissions"][0]  # type: ignore[index]
    ledger["corrections"] = [
        {
            "id": _uuid("bad-correction"),
            "item_id": item["id"],
            "original_submission_id": submission["id"],
            "reviewer_id": _OWNER_ID,
            "verdict": "gecko_absent",
            "representative_sec": None,
            "bbox": None,
            "reason": "정정",
            "expected_submission_digest": _digest("not-the-effective-digest"),
            "digest": submission["digest"],
            "created_at": "2026-08-23T01:01:00Z",
        }
    ]

    with pytest.raises(ScoreContractError, match="correction|digest"):
        score_audit(manifest, ledger)


def test_wilson95_handles_zero_full_small_n_and_empty_without_nan() -> None:
    assert wilson_interval95(0, 0) is None
    zero = wilson_interval95(0, 3)
    full = wilson_interval95(3, 3)
    small = wilson_interval95(1, 3)
    assert zero == pytest.approx((0.0, 0.5614970317550454))
    assert full == pytest.approx((0.4385029682449546, 1.0))
    assert small == pytest.approx((0.06149194472039621, 0.7923403991979523))
    assert all(0 <= bound <= 1 for interval in (zero, full, small) for bound in interval)


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_all_keys(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(_all_keys(child) for child in value))
    return set()


def test_export_is_read_only_injected_private_first_0600_no_overwrite_and_safe(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    ledger = _ledger(manifest)

    class Reader:
        calls: list[str] = []

        def export_batch_read_only(self, batch_id: str) -> dict[str, object]:
            self.calls.append(batch_id)
            return deepcopy(ledger)

    reader = Reader()
    private_path = tmp_path / "score-ledger.private.json"
    safe_path = tmp_path / "score-aggregate.safe.json"
    score = export_score_batch(
        manifest,
        batch_id=_BATCH_ID,
        reader=reader,
        private_ledger_path=private_path,
        safe_aggregate_path=safe_path,
    )

    assert reader.calls == [_BATCH_ID]
    assert score.negative_present == 6
    assert stat.S_IMODE(private_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(safe_path.stat().st_mode) == 0o600
    assert json.loads(private_path.read_text(encoding="utf-8")) == ledger
    safe = json.loads(safe_path.read_text(encoding="utf-8"))
    assert safe["batch_id"] == _BATCH_ID
    assert safe["random_negative"]["valid"] == 120
    assert safe["positive_control"]["detected"] == 29
    assert safe["descriptive"]["bbox_coverage"]["valid"] == 35
    assert set(safe["descriptive"]["camera_night_counts"]) == {
        f"night-{index:03d}" for index in range(1, 7)
    }
    forbidden = {
        "clip_id", "source", "source_key", "source_hash", "reviewer_id",
        "owner_id", "assigned_reviewer_id", "bbox", "representative_sec",
        "started_at", "created_at", "media_sha256", "media_dhash",
    }
    assert _all_keys(safe).isdisjoint(forbidden)
    with pytest.raises(FileExistsError):
        export_score_batch(
            manifest,
            batch_id=_BATCH_ID,
            reader=reader,
            private_ledger_path=private_path,
            safe_aggregate_path=safe_path,
        )
    assert reader.calls == [_BATCH_ID]


def test_export_default_reader_fails_closed_before_outputs(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    private_path = tmp_path / "private.json"
    safe_path = tmp_path / "safe.json"

    with pytest.raises(ScoreContractError, match="read-only ledger reader"):
        export_score_batch(
            manifest,
            batch_id=_BATCH_ID,
            private_ledger_path=private_path,
            safe_aggregate_path=safe_path,
        )

    assert not private_path.exists()
    assert not safe_path.exists()


def test_direct_cli_entrypoint_loads_without_changing_repository_state() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/score_gme_negative_audit.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "--ledger-input" in result.stdout
