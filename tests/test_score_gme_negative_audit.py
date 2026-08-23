"""Strict scoring and privacy contracts for the GME-negative audit."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
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
    canonical_ledger_digest,
    export_score_batch,
    load_completed_safe_aggregate,
    load_strict_json,
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


def _media_bytes(index: int, stratum: str) -> bytes:
    return f"frozen-media:{stratum}:{index}\n".encode()


def _sql_digest(*parts: object) -> str:
    def canonical(value: object) -> str:
        if isinstance(value, Decimal):
            return format(value, "f")
        if isinstance(value, dict):
            return "{" + ",".join(
                f"{json.dumps(key, ensure_ascii=False)}:{canonical(value[key])}"
                for key in sorted(value)
            ) + "}"
        if value is None:
            return "null"
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)

    rendered = [
        canonical(value)
        for value in parts
    ]
    return hashlib.sha256("|".join(rendered).encode()).hexdigest()


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
        "media_sha256": hashlib.sha256(_media_bytes(index, stratum)).hexdigest(),
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


def _verdict_shape(verdict: str) -> tuple[Decimal | None, dict[str, Decimal] | None]:
    if verdict != "gecko_present":
        return None, None
    return Decimal("12.5"), {
        "x": Decimal("0.1"), "y": Decimal("0.2"),
        "width": Decimal("0.3"), "height": Decimal("0.4"),
    }


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
        submission_id = _uuid(f"submission:{frozen['ordinal']}")
        submissions.append(
            {
                "id": submission_id,
                "item_id": item_id,
                "reviewer_id": _OWNER_ID,
                "verdict": verdict,
                "representative_sec": representative_sec,
                "bbox": bbox,
                "digest": _sql_digest(
                    submission_id, item_id, _OWNER_ID, verdict,
                    representative_sec, bbox,
                ),
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
            "test_sheet_sha256": manifest["test_sheet_sha256"],
            "manifest_sha256": manifest["manifest_sha256"],
            "seed": manifest["seed"],
            "cutoff": manifest["cutoff"],
            "detector_identity": manifest["detector_identity"],
            "checkpoint_sha256": manifest["checkpoint_sha256"],
            "negative_pool_sha256": manifest["source_pools"]["random_negative"]["sha256"],
            "control_pool_sha256": manifest["source_pools"]["positive_control"]["sha256"],
            "selection_sha256": manifest["selection_sha256"],
            "protected_manifest_sha256": manifest["protected_manifest_sha256"],
            "expected_negative_count": 120,
            "expected_control_count": 30,
            "expected_total_count": 150,
            "candidate_negative_count": manifest["candidate_counts"]["random_negative"],
            "candidate_control_count": manifest["candidate_counts"]["positive_control"],
        },
        "batch_events": [
            {
                "id": _uuid("event:prepared"),
                "batch_id": _BATCH_ID,
                "event_type": "prepared",
                "actor_id": _OWNER_ID,
                "reason": None,
                "digest": _sql_digest(
                    _uuid("event:prepared"), _BATCH_ID, "prepared", _OWNER_ID, None,
                ),
                "created_at": "2026-08-23T00:58:00Z",
            },
            {
                "id": _uuid("event:opened"),
                "batch_id": _BATCH_ID,
                "event_type": "opened",
                "actor_id": _OWNER_ID,
                "reason": None,
                "digest": _sql_digest(
                    _uuid("event:opened"), _BATCH_ID, "opened", _OWNER_ID, None,
                ),
                "created_at": "2026-08-23T00:59:00Z",
            },
            {
                "id": _uuid("event:closed"),
                "batch_id": _BATCH_ID,
                "event_type": "closed",
                "actor_id": _OWNER_ID,
                "reason": "scoring export frozen",
                "digest": _sql_digest(
                    _uuid("event:closed"), _BATCH_ID, "closed", _OWNER_ID,
                    "scoring export frozen",
                ),
                "created_at": "2026-08-23T01:03:00Z",
            },
        ],
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
    first["digest"] = _sql_digest(
        first["id"], first["item_id"], _REVIEWER_ID, first["verdict"],
        first["representative_sec"], first["bbox"],
    )

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
    submission["digest"] = _sql_digest(
        submission["id"], submission["item_id"], _REVIEWER_ID, submission["verdict"],
        submission["representative_sec"], submission["bbox"],
    )
    correction_id = _uuid("correction:1")
    correction_digest = _sql_digest(
        correction_id, submission["id"], submission["digest"], "uncertain", None, None,
        "다시 보니 가림이 커.",
    )
    ledger["corrections"] = [
        {
            "id": correction_id,
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
    adjudication_id = _uuid("adjudication:1")
    adjudication_digest = _sql_digest(
        adjudication_id, submission["id"], correction_digest, "gecko_absent", None, None,
        "Owner 확인 결과 게코 없음.",
    )
    ledger["adjudications"] = [
        {
            "id": adjudication_id,
            "item_id": item["id"],
            "original_submission_id": submission["id"],
            "owner_id": _OWNER_ID,
            "final_verdict": "gecko_absent",
            "representative_sec": None,
            "bbox": None,
            "reason": "Owner 확인 결과 게코 없음.",
            "effective_submission_digest": correction_digest,
            "digest": adjudication_digest,
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


def _write_media_fixture(tmp_path: Path, manifest: dict[str, object]) -> tuple[Path, dict[str, Path]]:
    root = tmp_path / "private-media"
    root.mkdir()
    by_sha = {
        hashlib.sha256(_media_bytes(index, stratum)).hexdigest(): _media_bytes(index, stratum)
        for stratum, count in (("random_negative", 120), ("positive_control", 30))
        for index in range(count)
    }
    mapping: dict[str, Path] = {}
    for raw_item in manifest["items"]:  # type: ignore[index]
        item = dict(raw_item)
        path = root / f"{item['ordinal']:03d}.mp4"
        path.write_bytes(by_sha[str(item["media_sha256"])])
        mapping[str(item["clip_id"])] = path
    return root, mapping


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
    media_root, media_files = _write_media_fixture(tmp_path, manifest)
    private_path = tmp_path / "score-ledger.private.json"
    safe_path = tmp_path / "score-aggregate.safe.json"
    score = export_score_batch(
        manifest,
        batch_id=_BATCH_ID,
        reader=reader,
        private_ledger_path=private_path,
        safe_aggregate_path=safe_path,
        media_root=media_root,
        media_files=media_files,
    )

    assert reader.calls == [_BATCH_ID]
    assert score.negative_present == 6
    assert stat.S_IMODE(private_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(safe_path.stat().st_mode) == 0o600
    assert json.loads(
        private_path.read_text(encoding="utf-8"), parse_float=Decimal,
    ) == ledger
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
    started = tmp_path / ".score-ledger.private.json.started.private.json"
    complete = tmp_path / ".score-ledger.private.json.complete.private.json"
    failed = tmp_path / ".score-ledger.private.json.failed.private.json"
    assert json.loads(started.read_text(encoding="utf-8"))["status"] == "started"
    assert json.loads(complete.read_text(encoding="utf-8"))["status"] == "complete"
    assert not failed.exists()
    assert stat.S_IMODE(started.stat().st_mode) == 0o600
    assert stat.S_IMODE(complete.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        export_score_batch(
            manifest,
            batch_id=_BATCH_ID,
            reader=reader,
            private_ledger_path=private_path,
            safe_aggregate_path=safe_path,
            media_root=media_root,
            media_files=media_files,
        )
    assert reader.calls == [_BATCH_ID]


def test_export_default_reader_fails_closed_before_outputs(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    private_path = tmp_path / "private.json"
    safe_path = tmp_path / "safe.json"
    media_root, media_files = _write_media_fixture(tmp_path, manifest)

    with pytest.raises(ScoreContractError, match="read-only ledger reader"):
        export_score_batch(
            manifest,
            batch_id=_BATCH_ID,
            private_ledger_path=private_path,
            safe_aggregate_path=safe_path,
            media_root=media_root,
            media_files=media_files,
        )

    assert not private_path.exists()
    assert not safe_path.exists()


def test_export_rejects_output_aliases_before_reader_or_any_write(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    calls: list[str] = []

    class Reader:
        def export_batch_read_only(self, batch_id: str) -> dict[str, object]:
            calls.append(batch_id)
            return _ledger(manifest)

    media_root, media_files = _write_media_fixture(tmp_path, manifest)
    output = tmp_path / "same.json"
    with pytest.raises(ScoreContractError, match="distinct output"):
        export_score_batch(
            manifest, batch_id=_BATCH_ID, reader=Reader(),
            private_ledger_path=output,
            safe_aggregate_path=tmp_path / "nested" / ".." / "same.json",
            media_root=media_root, media_files=media_files,
        )
    assert calls == []
    assert not output.exists()


def test_export_never_reuses_a_pair_with_a_legacy_invalid_marker(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    private_path = tmp_path / "private.json"
    safe_path = tmp_path / "safe.json"
    (tmp_path / "private.json.invalid").write_text("invalid\n", encoding="utf-8")
    media_root, media_files = _write_media_fixture(tmp_path, manifest)

    class Reader:
        def export_batch_read_only(self, batch_id: str) -> dict[str, object]:
            pytest.fail("legacy failure evidence must block work")

    with pytest.raises(FileExistsError):
        export_score_batch(
            manifest, batch_id=_BATCH_ID, reader=Reader(),
            private_ledger_path=private_path, safe_aggregate_path=safe_path,
            media_root=media_root, media_files=media_files,
        )

    assert not private_path.exists()
    assert not safe_path.exists()
    assert not (tmp_path / ".private.json.started.private.json").exists()


def test_export_publishes_private_first_safe_last_and_complete_is_required(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    media_root, media_files = _write_media_fixture(tmp_path, manifest)
    private_path = tmp_path / "private.json"
    safe_path = tmp_path / "safe.json"
    complete = tmp_path / ".private.json.complete.private.json"
    observed: list[str] = []

    def observe(source: Path, destination: Path) -> None:
        if destination == private_path:
            assert not private_path.exists()
            assert not safe_path.exists()
            observed.append("private")
        else:
            assert private_path.exists()
            assert not safe_path.exists()
            assert not complete.exists()
            observed.append("safe")
        os.link(source, destination)

    class Reader:
        def export_batch_read_only(self, batch_id: str) -> dict[str, object]:
            return _ledger(manifest)

    export_score_batch(
        manifest, batch_id=_BATCH_ID, reader=Reader(),
        private_ledger_path=private_path, safe_aggregate_path=safe_path,
        media_root=media_root, media_files=media_files,
        publish_replace=observe,
    )

    assert observed == ["private", "safe"]
    assert private_path.exists() and safe_path.exists() and complete.exists()
    assert load_completed_safe_aggregate(private_path, safe_path)["batch_id"] == _BATCH_ID
    complete.unlink()
    with pytest.raises(ScoreContractError, match="complete marker"):
        load_completed_safe_aggregate(private_path, safe_path)


def test_export_safe_publish_failure_keeps_only_private_final_and_failed_evidence(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    media_root, media_files = _write_media_fixture(tmp_path, manifest)
    private_path = tmp_path / "private.json"
    safe_path = tmp_path / "safe.json"
    publications = 0

    def fail_second(source: Path, destination: Path) -> None:
        nonlocal publications
        publications += 1
        if publications == 2:
            raise OSError("injected second publication failure")
        os.replace(source, destination)

    class Reader:
        def export_batch_read_only(self, batch_id: str) -> dict[str, object]:
            return _ledger(manifest)

    with pytest.raises(ScoreContractError, match="publication failed"):
        export_score_batch(
            manifest, batch_id=_BATCH_ID, reader=Reader(),
            private_ledger_path=private_path, safe_aggregate_path=safe_path,
            media_root=media_root, media_files=media_files,
            publish_replace=fail_second,
        )
    assert private_path.exists()
    assert not safe_path.exists()
    marker = tmp_path / ".private.json.failed.private.json"
    assert json.loads(marker.read_text(encoding="utf-8"))["status"] == "failed"
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600
    assert not (tmp_path / ".private.json.complete.private.json").exists()

    with pytest.raises(FileExistsError):
        export_score_batch(
            manifest, batch_id=_BATCH_ID, reader=Reader(),
            private_ledger_path=private_path, safe_aggregate_path=safe_path,
            media_root=media_root, media_files=media_files,
        )


def test_export_failure_marker_survives_cleanup_permission_failure(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    media_root, media_files = _write_media_fixture(tmp_path, manifest)
    private_path = tmp_path / "permission.private.json"
    safe_path = tmp_path / "permission.safe.json"

    class Reader:
        def export_batch_read_only(self, batch_id: str) -> dict[str, object]:
            return _ledger(manifest)

    def deny_failed_cleanup(path: Path) -> None:
        raise PermissionError(f"cannot unlink {path.name}")

    with pytest.raises(ScoreContractError, match="publication failed"):
        export_score_batch(
            manifest, batch_id=_BATCH_ID, reader=Reader(),
            private_ledger_path=private_path, safe_aggregate_path=safe_path,
            media_root=media_root, media_files=media_files,
            remove_marker=deny_failed_cleanup,
        )

    failed = tmp_path / ".permission.private.json.failed.private.json"
    assert json.loads(failed.read_text(encoding="utf-8"))["status"] == "failed"
    assert not safe_path.exists()
    assert not (tmp_path / ".permission.private.json.complete.private.json").exists()


def test_export_detects_safe_name_race_and_removes_private_alias(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    media_root, media_files = _write_media_fixture(tmp_path, manifest)
    private_path = tmp_path / "private.json"
    safe_path = tmp_path / "safe.json"

    def replace_claim(source: Path, destination: Path) -> None:
        if destination == safe_path:
            os.link(private_path, destination)
            raise FileExistsError(destination)
        os.link(source, destination)

    class Reader:
        def export_batch_read_only(self, batch_id: str) -> dict[str, object]:
            return _ledger(manifest)

    with pytest.raises(ScoreContractError, match="publication race"):
        export_score_batch(
            manifest, batch_id=_BATCH_ID, reader=Reader(),
            private_ledger_path=private_path, safe_aggregate_path=safe_path,
            media_root=media_root, media_files=media_files,
            publish_replace=replace_claim,
    )
    assert private_path.exists()
    assert not safe_path.exists()
    failed = tmp_path / ".private.json.failed.private.json"
    assert json.loads(failed.read_text(encoding="utf-8"))["status"] == "failed"


def test_export_requires_exact_real_media_and_rejects_symlink(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    media_root, media_files = _write_media_fixture(tmp_path, manifest)
    first_clip = str(manifest["items"][0]["clip_id"])  # type: ignore[index]
    target = media_files[first_clip]
    alias = media_root / "alias.mp4"
    alias.symlink_to(target)
    media_files[first_clip] = alias

    class Reader:
        def export_batch_read_only(self, batch_id: str) -> dict[str, object]:
            pytest.fail("media must fail before export")

    with pytest.raises(ScoreContractError, match="media"):
        export_score_batch(
            manifest, batch_id=_BATCH_ID, reader=Reader(),
            private_ledger_path=tmp_path / "private.json",
            safe_aggregate_path=tmp_path / "safe.json",
            media_root=media_root, media_files=media_files,
        )


def test_media_verification_error_does_not_disclose_private_path(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    media_root, media_files = _write_media_fixture(tmp_path, manifest)
    first_clip = str(manifest["items"][0]["clip_id"])  # type: ignore[index]
    missing = media_root / "secret-owner-path.mp4"
    media_files[first_clip] = missing

    class Reader:
        def export_batch_read_only(self, batch_id: str) -> dict[str, object]:
            pytest.fail("media must fail before export")

    with pytest.raises(ScoreContractError, match="media file verification") as caught:
        export_score_batch(
            manifest, batch_id=_BATCH_ID, reader=Reader(),
            private_ledger_path=tmp_path / "private.json",
            safe_aggregate_path=tmp_path / "safe.json",
            media_root=media_root, media_files=media_files,
        )
    assert "secret-owner-path" not in str(caught.value)


def test_duplicate_json_keys_fail_before_normalization(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"batch":{"id":"first","id":"second"}}', encoding="utf-8")

    with pytest.raises(ScoreContractError, match="duplicate JSON key"):
        load_strict_json(path, "ledger")


def test_python_digest_matches_the_sql_utf8_fixture_literal() -> None:
    assert canonical_ledger_digest(
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "게코 있음",
        None,
        {"x": 0.1},
    ) == "b691aa204934cc304b2863d54a50ffd870973343c8ff7ffe1d9dacdb27622611"


def test_ledger_json_and_digest_preserve_tiny_decimal_scale_without_exponents(
    tmp_path: Path,
) -> None:
    path = tmp_path / "decimal-ledger.json"
    path.write_text(
        '{"representative_sec":0.0000001000,"bbox":'
        '{"x":0.0000001000,"y":0.0000002000,'
        '"width":0.0000003000,"height":0.0000004000}}',
        encoding="utf-8",
    )

    loaded = load_strict_json(path, "ledger")

    assert loaded == {
        "representative_sec": Decimal("0.0000001000"),
        "bbox": {
            "x": Decimal("0.0000001000"), "y": Decimal("0.0000002000"),
            "width": Decimal("0.0000003000"), "height": Decimal("0.0000004000"),
        },
    }
    assert canonical_ledger_digest(
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
        "gecko_present",
        loaded["representative_sec"],  # type: ignore[index]
        loaded["bbox"],  # type: ignore[index]
    ) == "3dfb8aa8e29ec9e98acf4321c9df9691fcbe74ef5eb84d4a29b4f4866c86052e"


def test_ledger_json_rejects_non_finite_constants(tmp_path: Path) -> None:
    path = tmp_path / "constant.json"
    path.write_text('{"representative_sec":NaN}', encoding="utf-8")

    with pytest.raises(ScoreContractError, match="invalid"):
        load_strict_json(path, "ledger")


def test_score_validates_decimal_geometry_digest_before_domain_math(
    manifest: dict[str, object],
) -> None:
    ledger = _ledger(manifest)
    submission = ledger["submissions"][0]  # type: ignore[index]
    submission["representative_sec"] = Decimal("0.0000001000")
    submission["bbox"] = {
        "x": Decimal("0.0000001000"), "y": Decimal("0.0000002000"),
        "width": Decimal("0.0000003000"), "height": Decimal("0.0000004000"),
    }
    submission["digest"] = _sql_digest(
        submission["id"], submission["item_id"], submission["reviewer_id"],
        submission["verdict"], submission["representative_sec"], submission["bbox"],
    )

    assert score_audit(manifest, ledger).negative_present == 6


def test_manifest_selection_episode_and_ledger_batch_pins_are_recomputed(
    manifest: dict[str, object],
) -> None:
    bad_selection = deepcopy(manifest)
    bad_selection["selection_sha256"] = _digest("forged-selection")
    unsigned = dict(bad_selection)
    unsigned.pop("manifest_sha256")
    bad_selection["manifest_sha256"] = hashlib.sha256(_canonical_json(unsigned)).hexdigest()
    with pytest.raises(ScoreContractError, match="selection SHA"):
        score_audit(bad_selection, _ledger(bad_selection))

    bad_episode = deepcopy(manifest)
    negatives = [item for item in bad_episode["items"] if item["stratum"] == "random_negative"]  # type: ignore[index]
    for item in negatives[:3]:
        item["episode_key"] = "same-episode"
        candidate = {key: item[key] for key in item if key not in {"ordinal", "selection_provenance"}}
        item["selection_provenance"] = hashlib.sha256(_canonical_json({
            "seed": bad_episode["seed"], "ordinal": item["ordinal"], "candidate": candidate,
        })).hexdigest()
    unsigned = dict(bad_episode)
    unsigned.pop("manifest_sha256")
    bad_episode["manifest_sha256"] = hashlib.sha256(_canonical_json(unsigned)).hexdigest()
    with pytest.raises(ScoreContractError, match="episode cap"):
        score_audit(bad_episode, _ledger(bad_episode))

    ledger = _ledger(manifest)
    ledger["batch"]["test_sheet_sha256"] = _digest("wrong-sheet")  # type: ignore[index]
    with pytest.raises(ScoreContractError, match="batch pin"):
        score_audit(manifest, ledger)


@pytest.mark.parametrize("field", ["id", "representative_sec", "digest"])
def test_submission_canonical_digest_rejects_tampered_row(
    manifest: dict[str, object], field: str,
) -> None:
    ledger = _ledger(manifest)
    submission = ledger["submissions"][0]  # type: ignore[index]
    submission[field] = {
        "id": _uuid("tampered-submission-id"),
        "representative_sec": Decimal("13.0"),
        "digest": _digest("forged-digest"),
    }[field]
    with pytest.raises(ScoreContractError, match="submission digest"):
        score_audit(manifest, ledger)


def test_canonical_digest_rejects_valid_shape_verdict_and_reason_tampering(
    manifest: dict[str, object],
) -> None:
    verdict_ledger = _ledger(manifest)
    absent = next(
        row for row in verdict_ledger["submissions"]  # type: ignore[union-attr]
        if row["verdict"] == "gecko_absent"
    )
    absent["verdict"] = "uncertain"
    with pytest.raises(ScoreContractError, match="submission digest"):
        score_audit(manifest, verdict_ledger)

    reason_ledger = _ledger(manifest)
    item = reason_ledger["items"][0]  # type: ignore[index]
    submission = reason_ledger["submissions"][0]  # type: ignore[index]
    correction_id = _uuid("reason-correction")
    correction = {
        "id": correction_id,
        "item_id": item["id"],
        "original_submission_id": submission["id"],
        "reviewer_id": _OWNER_ID,
        "verdict": "uncertain",
        "representative_sec": None,
        "bbox": None,
        "reason": "원본 정정 이유",
        "expected_submission_digest": submission["digest"],
        "digest": _sql_digest(
            correction_id, submission["id"], submission["digest"],
            "uncertain", None, None, "원본 정정 이유",
        ),
        "created_at": "2026-08-23T01:01:00Z",
    }
    reason_ledger["corrections"] = [correction]
    correction["reason"] = "변조된 이유"
    with pytest.raises(ScoreContractError, match="correction digest"):
        score_audit(manifest, reason_ledger)


def test_batch_event_uuid_uniqueness_and_order_are_independent_of_digest(
    manifest: dict[str, object],
) -> None:
    duplicate = _ledger(manifest)
    first, second = duplicate["batch_events"][:2]  # type: ignore[index]
    second["id"] = first["id"]
    second["digest"] = _sql_digest(
        second["id"], second["batch_id"], second["event_type"], second["actor_id"], None,
    )
    with pytest.raises(ScoreContractError, match="batch event id is not unique"):
        score_audit(manifest, duplicate)

    reordered = _ledger(manifest)
    reordered["batch_events"].reverse()  # type: ignore[union-attr]
    with pytest.raises(ScoreContractError, match="order"):
        score_audit(manifest, reordered)


def test_scorer_requires_latest_batch_event_closed(manifest: dict[str, object]) -> None:
    opened = _ledger(manifest)
    opened["batch_events"] = opened["batch_events"][:-1]  # type: ignore[index]

    with pytest.raises(ScoreContractError, match="latest batch event.*closed"):
        score_audit(manifest, opened)

    assert score_audit(manifest, _ledger(manifest)).random_negative == 120


def _dataset_decision(
    ledger: dict[str, object], item_index: int, decision: str, label: str,
) -> dict[str, object]:
    item = ledger["items"][item_index]  # type: ignore[index]
    submission = ledger["submissions"][item_index]  # type: ignore[index]
    decision_id = _uuid(label)
    return {
        "id": decision_id,
        "item_id": item["id"],
        "owner_id": _OWNER_ID,
        "decision": decision,
        "reason": f"{decision} 검증",
        "effective_submission_digest": submission["digest"],
        "adjudication_id": None,
        "digest": _sql_digest(
            decision_id, item["id"], decision, submission["digest"], f"{decision} 검증",
        ),
        "created_at": "2026-08-23T01:04:00Z" if label.endswith("1") else "2026-08-23T01:05:00Z",
    }


def test_dataset_decision_item_is_unique_even_with_distinct_ids_and_digests(
    manifest: dict[str, object],
) -> None:
    ledger = _ledger(manifest)
    ledger["dataset_decisions"] = [
        _dataset_decision(ledger, 0, "defer", "decision:1"),
        _dataset_decision(ledger, 0, "exclude_quality", "decision:2"),
    ]

    with pytest.raises(ScoreContractError, match="dataset decision item.*unique"):
        score_audit(manifest, ledger)


@pytest.mark.parametrize("decision", ["defer", "exclude_quality"])
def test_dataset_decision_rejects_every_control_value(
    manifest: dict[str, object], decision: str,
) -> None:
    ledger = _ledger(manifest)
    control_index = next(
        index for index, item in enumerate(ledger["items"])  # type: ignore[arg-type]
        if item["stratum"] == "positive_control"
    )
    ledger["dataset_decisions"] = [
        _dataset_decision(ledger, control_index, decision, "control-decision:1"),
    ]

    with pytest.raises(ScoreContractError, match="control cannot have a Dataset decision"):
        score_audit(manifest, ledger)


@pytest.mark.parametrize("decision", ["defer", "exclude_quality"])
def test_dataset_decision_rejects_non_owner_without_adjudication_for_every_value(
    manifest: dict[str, object], decision: str,
) -> None:
    ledger = _ledger(manifest)
    item_index = next(
        index for index, submission in enumerate(ledger["submissions"])  # type: ignore[arg-type]
        if submission["verdict"] == "gecko_absent"
    )
    item = ledger["items"][item_index]  # type: ignore[index]
    submission = ledger["submissions"][item_index]  # type: ignore[index]
    item["assigned_reviewer_id"] = _REVIEWER_ID
    submission["reviewer_id"] = _REVIEWER_ID
    submission["digest"] = _sql_digest(
        submission["id"], submission["item_id"], _REVIEWER_ID,
        submission["verdict"], None, None,
    )
    ledger["dataset_decisions"] = [
        _dataset_decision(ledger, item_index, decision, "non-owner-decision:1"),
    ]

    with pytest.raises(ScoreContractError, match="Dataset decision requires adjudication"):
        score_audit(manifest, ledger)


def test_media_bytes_are_rehashed_after_read_only_export(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    media_root, media_files = _write_media_fixture(tmp_path, manifest)
    first_clip = str(manifest["items"][0]["clip_id"])  # type: ignore[index]

    class MutatingReader:
        def export_batch_read_only(self, batch_id: str) -> dict[str, object]:
            media_files[first_clip].write_bytes(b"mutated-in-place")
            return _ledger(manifest)

    with pytest.raises(ScoreContractError, match="media mutated"):
        export_score_batch(
            manifest, batch_id=_BATCH_ID, reader=MutatingReader(),
            private_ledger_path=tmp_path / "private.json",
            safe_aggregate_path=tmp_path / "safe.json",
            media_root=media_root, media_files=media_files,
        )
    assert not (tmp_path / "private.json").exists()
    assert not (tmp_path / "safe.json").exists()


def test_direct_cli_entrypoint_loads_without_changing_repository_state() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/score_gme_negative_audit.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "--ledger-input" in result.stdout
    assert "--media-root" in result.stdout
    assert "--media-map" in result.stdout
