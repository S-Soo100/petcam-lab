from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import UUID

import cv2
import numpy as np
import pytest

import scripts.prepare_gme_negative_audit_batch as prepare_module

from scripts.gme_negative_audit_sampling import CHECKPOINT_SHA256, DETECTOR_IDENTITY
from scripts.prepare_gme_negative_audit_batch import (
    PreflightConfig,
    PreflightError,
    PinnedJson,
    PROTECTED_ROLE_COUNTS,
    _SupabaseAuditDb,
    _canonicalize_database_timestamp,
    _probe_media_bytes,
    freeze_batch_manifest,
    import_batch,
    main,
    run_preflight,
)


CUTOFF = "2026-08-15T00:00:00Z"
OWNER_ID = "00000000-0000-4000-8000-000000000001"
SEED = "gme-negative-audit-calibration-v1"


class FakeDb:
    def __init__(self, negatives: list[dict[str, object]], controls: list[dict[str, object]]):
        self.negatives = negatives
        self.controls = controls
        self.read_calls: list[tuple[str, dict[str, object]]] = []
        self.write_calls: list[tuple[str, dict[str, object]]] = []

    def read(self, operation: str, params: dict[str, object]) -> list[dict[str, object]]:
        self.read_calls.append((operation, dict(params)))
        if operation == "owner_exists":
            return [{"exists": True}]
        if operation == "negative_candidates":
            return list(self.negatives)
        if operation == "positive_controls":
            return list(self.controls)
        raise AssertionError(f"unexpected read operation: {operation}")

    def write_rpc(self, operation: str, params: dict[str, object]) -> list[dict[str, object]]:
        self.write_calls.append((operation, dict(params)))
        return [{"batch_id": "00000000-0000-4000-8000-000000000999", "status": "prepared"}]

    def insert(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("mutation method must never be used")


class ClosingBody(io.BytesIO):
    was_closed = False

    def close(self) -> None:
        self.was_closed = True
        super().close()


class FakeR2:
    def __init__(self, payload_by_key: dict[str, bytes]):
        self.payload_by_key = payload_by_key
        self.read_calls: list[tuple[str, str]] = []
        self.write_calls: list[tuple[str, dict[str, object]]] = []
        self.bodies: list[ClosingBody] = []

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.read_calls.append(("HEAD", Key))
        payload = self.payload_by_key[Key]
        return {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "ContentLength": len(payload),
            "ContentType": "video/mp4",
        }

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.read_calls.append(("GET", Key))
        body = ClosingBody(self.payload_by_key[Key])
        self.bodies.append(body)
        return {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "ContentLength": len(self.payload_by_key[Key]),
            "Body": body,
        }

    def put_object(self, **kwargs: object) -> None:
        self.write_calls.append(("PUT", dict(kwargs)))


def _json_new(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    path.write_bytes(raw)
    path.chmod(0o600)
    return hashlib.sha256(raw).hexdigest()


def _media_pair(index: int) -> dict[str, str]:
    token = hashlib.sha256(f"protected-{index}".encode()).hexdigest()
    source = str(UUID(int=900_000 + index))
    key = f"protected/{index}.mp4"
    return {
        "media_sha256": token,
        "media_dhash": token[:16],
        "source_identity_sha256": hashlib.sha256(
            b"gme-negative-audit-source-identity-v1\0" + source.encode()
        ).hexdigest(),
        "r2_key_sha256": hashlib.sha256(
            b"gme-negative-audit-r2-key-v1\0" + key.encode()
        ).hexdigest(),
    }


def _pinned_inputs(root: Path) -> tuple[PinnedJson, tuple[PinnedJson, ...]]:
    training_path = root / "pins" / "training.private.json"
    training_sha = _json_new(
        training_path,
        {
            "schema_version": "gme-negative-audit-training-pin-v1",
            "status": "frozen",
            "cutoff": CUTOFF,
            "detector_identity": DETECTOR_IDENTITY,
            "checkpoint_sha256": CHECKPOINT_SHA256,
            "record_count": 2,
            "records": [_media_pair(0), _media_pair(1)],
        },
    )
    protected: list[PinnedJson] = []
    offset = 1000
    for role, count in PROTECTED_ROLE_COUNTS.items():
        role_count = count if count is not None else 1
        path = root / "pins" / f"{role}.private.json"
        raw_sha = _json_new(
            path,
            {
                "schema_version": "gme-negative-audit-protected-pin-v1",
                "status": "frozen",
                "role": role,
                "record_count": role_count,
                "records": [_media_pair(offset + index) for index in range(role_count)],
            },
        )
        protected.append(PinnedJson(role=role, path=path, raw_sha256=raw_sha))
        offset += role_count + 100
    return (
        PinnedJson(role="train", path=training_path, raw_sha256=training_sha),
        tuple(protected),
    )


def _row(index: int, *, control: bool = False) -> dict[str, object]:
    started = datetime(2026, 8, 16, 1, tzinfo=UTC) + timedelta(minutes=index * 7)
    clip_id = str(UUID(int=10_000 + index + (100_000 if control else 0)))
    run_id = str(UUID(int=20_000 + index + (100_000 if control else 0)))
    return {
        "clip_id": clip_id,
        "camera_id": str(UUID(int=30_000 + (index % 12))),
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "duration_sec": 60.0,
        "r2_key": f"private/{clip_id}.mp4",
        "clip_purpose": "production",
        "dataset_role": "development" if control else None,
        "current_job_status": "succeeded",
        "current_job_detector_identity": DETECTOR_IDENTITY,
        "current_result_run_id": run_id,
        "current_run_id": run_id,
        "current_run_status": "ok",
        "current_detector_identity": DETECTOR_IDENTITY,
        "current_detected": True if control else False,
        "consensus_status": "agreed" if control else None,
        "consensus_final_decision": "label" if control else None,
        "consensus_visibility": "visible" if control else None,
        "human_gt_digest": hashlib.sha256(f"gt-{index}".encode()).hexdigest() if control else None,
        "research_quarantined": False,
    }


def _clients(negative_count: int = 120, control_count: int = 30):
    negatives = [_row(index) for index in range(negative_count)]
    controls = [_row(index, control=True) for index in range(control_count)]
    rows = [*negatives, *controls]
    payload_by_key = {str(row["r2_key"]): f"media:{row['clip_id']}".encode() for row in rows}
    return FakeDb(negatives, controls), FakeR2(payload_by_key)


def _known_visible_negative_clients(count: int):
    rows = [_row(index) for index in range(count)]
    for index, row in enumerate(rows):
        row.update(
            {
                "dataset_role": "development",
                "consensus_status": "agreed",
                "consensus_final_decision": "label",
                "consensus_visibility": "visible",
                "human_gt_digest": hashlib.sha256(
                    f"known-visible-gt-{index}".encode()
                ).hexdigest(),
            }
        )
    payload_by_key = {
        str(row["r2_key"]): f"media:{row['clip_id']}".encode() for row in rows
    }
    return FakeDb(rows, [dict(row) for row in rows]), FakeR2(payload_by_key)


def _config(tmp_path: Path, *, frozen_sheet: bool = False) -> PreflightConfig:
    training, protected = _pinned_inputs(tmp_path)
    sheet = tmp_path / "TEST-SHEET.md"
    contract = {
        "schema_version": "gme-negative-audit-test-sheet-v1",
        "freeze_status": "FROZEN" if frozen_sheet else "UNFROZEN",
        "owner_approval": "APPROVED" if frozen_sheet else "PENDING",
        "reviewed_import_schema": "gme-negative-audit-v1" if frozen_sheet else "PENDING",
        "seed": SEED,
        "selection_algorithm_version": "gme-negative-audit-selection-v1",
        "negative_count": 120,
        "control_count": 30,
        "episode_cap": 2,
        "detector_identity": DETECTOR_IDENTITY,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "training_manifest_sha256": training.raw_sha256,
        "cutoff": CUTOFF,
        "protected_manifest_sha256": {pin.role: pin.raw_sha256 for pin in protected},
        "approved_reviewer_ids": [OWNER_ID],
    }
    sheet.write_text(
        "# test\n\n<!-- GME_NEGATIVE_AUDIT_MACHINE_CONTRACT_BEGIN\n"
        + json.dumps(contract, sort_keys=True, separators=(",", ":"))
        + "\nGME_NEGATIVE_AUDIT_MACHINE_CONTRACT_END -->\n",
        encoding="utf-8",
    )
    sheet.chmod(0o600)
    return PreflightConfig(
        attempt_root=tmp_path / "attempt",
        training_manifest=training,
        protected_manifests=protected,
        test_sheet_path=sheet,
        owner_id=OWNER_ID,
        r2_bucket="private-bucket",
    )


def _fake_probe(payload: bytes) -> str:
    return hashlib.sha256(b"dhash:" + payload).hexdigest()[:16]


def test_default_preflight_is_service_read_only_and_publishes_private_complete_artifacts(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    db, r2 = _clients()

    result = run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)

    assert result["status"] == "GME_NEGATIVE_AUDIT_PREFLIGHT_READY"
    assert db.write_calls == []
    assert r2.write_calls == []
    assert {operation for operation, _ in db.read_calls} == {
        "owner_exists",
        "negative_candidates",
        "positive_controls",
    }
    assert {method for method, _ in r2.read_calls} == {"HEAD", "GET"}
    assert all(body.was_closed for body in r2.bodies)
    for name in (
        "preflight.started.private.json",
        "inventory.private.json",
        "availability.private.json",
        "preflight.complete.private.json",
    ):
        path = config.attempt_root / name
        assert path.is_file()
        assert path.stat().st_mode & 0o777 == 0o600
    assert not (config.attempt_root / "batch-manifest.private.json").exists()
    availability = json.loads((config.attempt_root / "availability.private.json").read_bytes())
    raw = json.dumps(availability, sort_keys=True)
    assert availability["eligible_counts"] == {"random_negative": 120, "positive_control": 30}
    assert availability["camera_count"] == 12
    assert availability["r2_head_count"] == 150
    assert availability["r2_get_count"] == 150
    assert availability["db_write_count"] == availability["r2_write_count"] == 0
    for forbidden in ("clip_id", "camera_id", "r2_key", "gme_run_id", OWNER_ID, "private/"):
        assert forbidden not in raw


def test_known_visible_gme_negatives_are_sampled_gt_blind_before_controls(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path / "canonical", frozen_sheet=True)
    config.test_sheet_path.chmod(0o644)
    db, r2 = _known_visible_negative_clients(150)

    availability = run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)
    sheet_sha = hashlib.sha256(config.test_sheet_path.read_bytes()).hexdigest()
    manifest = freeze_batch_manifest(config, expected_test_sheet_sha256=sheet_sha)

    assert availability["status"] == "GME_NEGATIVE_AUDIT_PREFLIGHT_READY"
    assert availability["eligible_counts"] == {
        "random_negative": 150,
        "positive_control": 150,
    }
    assert availability["post_negative_control_count"] == 30
    assert availability["r2_head_count"] == availability["r2_get_count"] == 150
    assert manifest["candidate_counts"] == {
        "random_negative": 150,
        "positive_control": 30,
    }
    assert manifest["source_pools"]["random_negative"]["count"] == 150
    assert manifest["source_pools"]["positive_control"]["count"] == 30
    random_items = [
        item for item in manifest["items"] if item["stratum"] == "random_negative"
    ]
    control_items = [
        item for item in manifest["items"] if item["stratum"] == "positive_control"
    ]
    assert len(random_items) == 120
    assert len(control_items) == 30
    assert all(item["human_gt_digest"] is None for item in random_items)
    assert all(item["human_gt_digest"] is not None for item in control_items)
    assert {item["clip_id"] for item in random_items}.isdisjoint(
        item["clip_id"] for item in control_items
    )
    assert {item["clip_id"] for item in manifest["items"]} == {
        str(row["clip_id"]) for row in db.negatives
    }

    reversed_config = _config(tmp_path / "reversed", frozen_sheet=True)
    reversed_config.test_sheet_path.chmod(0o644)
    reversed_db, reversed_r2 = _known_visible_negative_clients(150)
    reversed_db.negatives.reverse()
    reversed_db.controls.reverse()
    run_preflight(
        reversed_config,
        db=reversed_db,
        r2=reversed_r2,
        media_probe=_fake_probe,
    )
    reversed_sheet_sha = hashlib.sha256(
        reversed_config.test_sheet_path.read_bytes()
    ).hexdigest()
    reversed_manifest = freeze_batch_manifest(
        reversed_config,
        expected_test_sheet_sha256=reversed_sheet_sha,
    )
    assert reversed_manifest == manifest


def test_control_shortage_is_evaluated_after_random_negative_selection(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    db, r2 = _known_visible_negative_clients(149)

    result = run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)

    assert result["eligible_counts"] == {
        "random_negative": 149,
        "positive_control": 149,
    }
    assert result["post_negative_control_count"] == 29
    assert result["status"] == "GME_NEGATIVE_AUDIT_SHORTAGE"
    assert not (config.attempt_root / "batch-manifest.private.json").exists()


def test_raw_sha_pin_failure_happens_before_attempt_or_external_reads(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config = PreflightConfig(
        attempt_root=config.attempt_root,
        training_manifest=PinnedJson(
            role="train", path=config.training_manifest.path, raw_sha256="0" * 64
        ),
        protected_manifests=config.protected_manifests,
        test_sheet_path=config.test_sheet_path,
        owner_id=config.owner_id,
        r2_bucket=config.r2_bucket,
    )
    db, r2 = _clients()

    with pytest.raises(PreflightError, match="PIN_MISMATCH"):
        run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)

    assert not config.attempt_root.exists()
    assert db.read_calls == db.write_calls == []
    assert r2.read_calls == r2.write_calls == []


def test_unavailable_rows_are_aggregated_and_never_promoted_to_negative(tmp_path: Path) -> None:
    config = _config(tmp_path)
    db, r2 = _clients(negative_count=121)
    db.negatives[0]["current_job_status"] = "failed_terminal"

    result = run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)

    assert result["status"] == "GME_NEGATIVE_AUDIT_PREFLIGHT_READY"
    availability = json.loads((config.attempt_root / "availability.private.json").read_bytes())
    assert availability["eligible_counts"]["random_negative"] == 120
    assert availability["unavailable_reasons"] == {"lineage_mismatch": 1}
    inventory = json.loads((config.attempt_root / "inventory.private.json").read_bytes())
    assert len(inventory["candidate_pools"]["random_negative"]) == 120


def test_job_and_run_detector_identity_must_both_match_the_immutable_pin(tmp_path: Path) -> None:
    config = _config(tmp_path)
    db, r2 = _clients(negative_count=121)
    db.negatives[0]["current_job_detector_identity"] = "f" * 64

    run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)

    availability = json.loads((config.attempt_root / "availability.private.json").read_bytes())
    assert availability["eligible_counts"]["random_negative"] == 120
    assert availability["unavailable_reasons"] == {"lineage_mismatch": 1}


def test_protected_near_duplicate_distance_two_is_unavailable_but_distance_three_is_allowed(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    db, r2 = _clients(negative_count=122)
    protected = json.loads(config.protected_manifests[0].path.read_bytes())["records"][0]
    protected_dhash = int(protected["media_dhash"], 16)
    first_payload = r2.payload_by_key[str(db.negatives[0]["r2_key"])]
    second_payload = r2.payload_by_key[str(db.negatives[1]["r2_key"])]

    def probe(payload: bytes) -> str:
        if payload == first_payload:
            return f"{protected_dhash ^ 0b11:016x}"
        if payload == second_payload:
            return f"{protected_dhash ^ 0b111:016x}"
        return _fake_probe(payload)

    run_preflight(config, db=db, r2=r2, media_probe=probe)

    availability = json.loads((config.attempt_root / "availability.private.json").read_bytes())
    assert availability["eligible_counts"]["random_negative"] == 121
    assert availability["unavailable_reasons"]["protected_near_duplicate"] == 1
    inventory = json.loads((config.attempt_root / "inventory.private.json").read_bytes())
    clip_ids = {row["clip_id"] for row in inventory["candidate_pools"]["random_negative"]}
    assert db.negatives[0]["clip_id"] not in clip_ids
    assert db.negatives[1]["clip_id"] in clip_ids


def test_protected_source_identity_is_rejected_before_any_r2_access(tmp_path: Path) -> None:
    config = _config(tmp_path)
    db, r2 = _clients(negative_count=121)
    protected_pin = config.protected_manifests[0]
    payload = json.loads(protected_pin.path.read_bytes())
    protected_row = payload["records"][0]
    protected_row["source_identity_sha256"] = hashlib.sha256(
        b"gme-negative-audit-source-identity-v1\0"
        + str(db.negatives[0]["clip_id"]).encode()
    ).hexdigest()
    protected_row["r2_key_sha256"] = hashlib.sha256(
        b"gme-negative-audit-r2-key-v1\0"
        + str(db.negatives[0]["r2_key"]).encode()
    ).hexdigest()
    new_sha = _json_new(protected_pin.path, payload)
    pins = tuple(
        PinnedJson(pin.role, pin.path, new_sha) if pin.role == protected_pin.role else pin
        for pin in config.protected_manifests
    )
    config = PreflightConfig(
        attempt_root=config.attempt_root,
        training_manifest=config.training_manifest,
        protected_manifests=pins,
        test_sheet_path=config.test_sheet_path,
        owner_id=config.owner_id,
        r2_bucket=config.r2_bucket,
    )

    result = run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)

    protected_key = str(db.negatives[0]["r2_key"])
    assert all(key != protected_key for _, key in r2.read_calls)
    assert result["protected_media_get_count"] == 0
    assert result["unavailable_reasons"] == {"protected_source_identity": 1}


def test_reported_protected_get_count_matches_post_get_media_overlap_ledger(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    db, r2 = _clients(negative_count=121)
    protected_pin = config.protected_manifests[0]
    payload = json.loads(protected_pin.path.read_bytes())
    candidate_key = str(db.negatives[0]["r2_key"])
    candidate_payload = r2.payload_by_key[candidate_key]
    overlapping_control = dict(db.negatives[0])
    overlapping_control.update(
        {
            "dataset_role": "development",
            "consensus_status": "agreed",
            "consensus_final_decision": "label",
            "consensus_visibility": "visible",
            "human_gt_digest": hashlib.sha256(b"overlap-gt").hexdigest(),
        }
    )
    db.controls.append(overlapping_control)
    payload["records"][0]["media_sha256"] = hashlib.sha256(candidate_payload).hexdigest()
    new_sha = _json_new(protected_pin.path, payload)
    pins = tuple(
        PinnedJson(pin.role, pin.path, new_sha) if pin.role == protected_pin.role else pin
        for pin in config.protected_manifests
    )
    config = PreflightConfig(
        attempt_root=config.attempt_root,
        training_manifest=config.training_manifest,
        protected_manifests=pins,
        test_sheet_path=config.test_sheet_path,
        owner_id=config.owner_id,
        r2_bucket=config.r2_bucket,
    )

    result = run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)

    assert r2.read_calls.count(("GET", candidate_key)) == 1
    assert result["protected_media_get_count"] == 1
    assert result["unavailable_reasons"] == {"protected_exact_duplicate": 2}


@pytest.mark.parametrize("mutation", ("missing", "malformed"))
def test_protected_identity_mutation_fails_before_db_or_r2_read(
    tmp_path: Path, mutation: str
) -> None:
    config = _config(tmp_path)
    protected_pin = config.protected_manifests[0]
    payload = json.loads(protected_pin.path.read_bytes())
    if mutation == "missing":
        del payload["records"][0]["r2_key_sha256"]
    else:
        payload["records"][0]["source_identity_sha256"] = "0" * 63
    new_sha = _json_new(protected_pin.path, payload)
    pins = tuple(
        PinnedJson(pin.role, pin.path, new_sha) if pin.role == protected_pin.role else pin
        for pin in config.protected_manifests
    )
    config = PreflightConfig(
        attempt_root=config.attempt_root,
        training_manifest=config.training_manifest,
        protected_manifests=pins,
        test_sheet_path=config.test_sheet_path,
        owner_id=config.owner_id,
        r2_bucket=config.r2_bucket,
    )
    db, r2 = _clients()

    with pytest.raises(PreflightError, match="PROTECTED_PIN_INVALID"):
        run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)

    assert db.read_calls == []
    assert r2.read_calls == []


@pytest.mark.parametrize("mutation", ("missing_source", "malformed_source", "missing_r2"))
def test_current_source_identity_mutation_is_unavailable_before_r2_read(
    tmp_path: Path, mutation: str
) -> None:
    config = _config(tmp_path)
    db, r2 = _clients(negative_count=121)
    key = str(db.negatives[0]["r2_key"])
    if mutation == "missing_source":
        del db.negatives[0]["clip_id"]
    elif mutation == "malformed_source":
        db.negatives[0]["clip_id"] = "not-a-uuid"
    else:
        del db.negatives[0]["r2_key"]

    result = run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)

    assert all(call_key != key for _, call_key in r2.read_calls)
    assert result["unavailable_reasons"] == {"source_contract_mismatch": 1}


def test_shortage_completes_safe_preflight_without_manifest_or_replacement(tmp_path: Path) -> None:
    config = _config(tmp_path)
    db, r2 = _clients(negative_count=119)

    result = run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)

    assert result["status"] == "GME_NEGATIVE_AUDIT_SHORTAGE"
    assert not (config.attempt_root / "batch-manifest.private.json").exists()
    with pytest.raises(PreflightError, match="ATTEMPT_EXISTS"):
        run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)
    assert db.write_calls == []


def test_freeze_requires_exact_frozen_test_sheet_and_creates_task1_manifest_once(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, frozen_sheet=True)
    config.test_sheet_path.chmod(0o644)
    db, r2 = _clients()
    run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)
    sheet_sha = hashlib.sha256(config.test_sheet_path.read_bytes()).hexdigest()

    manifest = freeze_batch_manifest(config, expected_test_sheet_sha256=sheet_sha)

    assert manifest["status"] == "prepared"
    assert manifest["test_sheet_sha256"] == sheet_sha
    assert len(manifest["items"]) == 150
    manifest_path = config.attempt_root / "batch-manifest.private.json"
    assert manifest_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(PreflightError, match="MANIFEST_EXISTS"):
        freeze_batch_manifest(config, expected_test_sheet_sha256=sheet_sha)


def test_freeze_rejects_unfrozen_or_wrong_reviewer_sheet_without_manifest(tmp_path: Path) -> None:
    config = _config(tmp_path)
    db, r2 = _clients()
    run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)
    sheet_sha = hashlib.sha256(config.test_sheet_path.read_bytes()).hexdigest()

    with pytest.raises(PreflightError, match="TEST_SHEET_NOT_FROZEN"):
        freeze_batch_manifest(config, expected_test_sheet_sha256=sheet_sha)

    assert not (config.attempt_root / "batch-manifest.private.json").exists()


def _ready_frozen_attempt(tmp_path: Path) -> tuple[PreflightConfig, str]:
    config = _config(tmp_path, frozen_sheet=True)
    db, r2 = _clients()
    run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)
    return config, hashlib.sha256(config.test_sheet_path.read_bytes()).hexdigest()


def _ready_import_attempt(tmp_path: Path) -> tuple[PreflightConfig, str, str]:
    config, sheet_sha = _ready_frozen_attempt(tmp_path)
    freeze_batch_manifest(config, expected_test_sheet_sha256=sheet_sha)
    manifest_sha = hashlib.sha256(
        (config.attempt_root / "batch-manifest.private.json").read_bytes()
    ).hexdigest()
    return config, sheet_sha, manifest_sha


def test_freeze_rejects_attempt_root_world_mode_before_reading_inventory(tmp_path: Path) -> None:
    config, sheet_sha = _ready_frozen_attempt(tmp_path)
    config.attempt_root.chmod(0o777)

    with pytest.raises(PreflightError, match="ATTEMPT_ROOT_SECURITY_INVALID"):
        freeze_batch_manifest(config, expected_test_sheet_sha256=sheet_sha)


def test_preflight_attempt_root_symlink_replacement_never_chmods_or_deletes_collateral(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    db, r2 = _clients()
    moved = tmp_path / "moved-created-attempt"
    victim = tmp_path / "victim.private"
    victim.write_bytes(b"do-not-change")
    victim.chmod(0o640)
    original_mkdir = Path.mkdir

    def replacing_mkdir(path: Path, *args: object, **kwargs: object) -> None:
        original_mkdir(path, *args, **kwargs)
        if path == config.attempt_root:
            path.rename(moved)
            path.symlink_to(victim)

    monkeypatch.setattr(Path, "mkdir", replacing_mkdir)

    with pytest.raises(
        PreflightError, match="ATTEMPT_CREATE_FAILED|ATTEMPT_ROOT_SECURITY_INVALID"
    ):
        run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)

    assert victim.read_bytes() == b"do-not-change"
    assert victim.stat().st_mode & 0o777 == 0o640
    assert config.attempt_root.is_symlink()
    assert moved.is_dir()
    assert db.read_calls == db.write_calls == []
    assert r2.read_calls == r2.write_calls == []


@pytest.mark.parametrize("replacement_kind", ("regular", "directory"))
def test_preflight_attempt_root_inode_swap_after_open_fails_before_artifact_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_kind: str,
) -> None:
    config = _config(tmp_path)
    db, r2 = _clients()
    moved = tmp_path / f"moved-created-{replacement_kind}"
    original_open = os.open
    original_mkdir = Path.mkdir
    replaced = False

    def replacing_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal replaced
        if dir_fd is None:
            fd = original_open(path, flags, mode)
        else:
            fd = original_open(path, flags, mode, dir_fd=dir_fd)
        if not replaced and Path(path) == config.attempt_root and flags & os.O_DIRECTORY:
            replaced = True
            config.attempt_root.rename(moved)
            if replacement_kind == "regular":
                config.attempt_root.write_bytes(b"replacement-collateral")
                config.attempt_root.chmod(0o640)
            else:
                original_mkdir(config.attempt_root, mode=0o700)
                (config.attempt_root / "sentinel").write_bytes(b"do-not-delete")
        return fd

    monkeypatch.setattr(os, "open", replacing_open)

    with pytest.raises(
        PreflightError,
        match="ATTEMPT_CREATE_FAILED|ATTEMPT_ROOT_IDENTITY_MISMATCH|ATTEMPT_ROOT_SECURITY_INVALID",
    ):
        run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)

    assert moved.is_dir()
    assert not any(moved.iterdir())
    if replacement_kind == "regular":
        assert config.attempt_root.read_bytes() == b"replacement-collateral"
        assert config.attempt_root.stat().st_mode & 0o777 == 0o640
    else:
        assert (config.attempt_root / "sentinel").read_bytes() == b"do-not-delete"
    assert db.read_calls == db.write_calls == []
    assert r2.read_calls == r2.write_calls == []


def test_freeze_rejects_attempt_root_inode_swap_even_when_markers_are_copied(
    tmp_path: Path,
) -> None:
    config, sheet_sha = _ready_frozen_attempt(tmp_path)
    original = tmp_path / "original-attempt"
    config.attempt_root.rename(original)
    shutil.copytree(original, config.attempt_root)
    config.attempt_root.chmod(0o700)

    with pytest.raises(PreflightError, match="ATTEMPT_ROOT_IDENTITY_MISMATCH"):
        freeze_batch_manifest(config, expected_test_sheet_sha256=sheet_sha)


@pytest.mark.parametrize("mutation", ("replace", "hardlink"))
def test_freeze_rejects_started_marker_identity_mutation(
    tmp_path: Path, mutation: str
) -> None:
    config, sheet_sha = _ready_frozen_attempt(tmp_path)
    started = config.attempt_root / "preflight.started.private.json"
    if mutation == "replace":
        payload = started.read_bytes()
        started.unlink()
        started.write_bytes(payload)
        started.chmod(0o600)
    else:
        os.link(started, config.attempt_root / "started-alias.private.json")

    with pytest.raises(
        PreflightError,
        match="ATTEMPT_ROOT_IDENTITY_MISMATCH|INVENTORY_NOT_FROZEN|ATTEMPT_FILE_INVALID",
    ):
        freeze_batch_manifest(config, expected_test_sheet_sha256=sheet_sha)


def test_freeze_rejects_complete_marker_same_bytes_inode_replacement(tmp_path: Path) -> None:
    config, sheet_sha = _ready_frozen_attempt(tmp_path)
    complete = config.attempt_root / "preflight.complete.private.json"
    payload = complete.read_bytes()
    complete.unlink()
    complete.write_bytes(payload)
    complete.chmod(0o600)

    with pytest.raises(PreflightError, match="INVENTORY_NOT_FROZEN"):
        freeze_batch_manifest(config, expected_test_sheet_sha256=sheet_sha)


@pytest.mark.parametrize("mutation", ("replace", "symlink", "hardlink", "mode"))
def test_freeze_rejects_inventory_identity_and_private_file_mutations(
    tmp_path: Path, mutation: str
) -> None:
    config, sheet_sha = _ready_frozen_attempt(tmp_path)
    inventory = config.attempt_root / "inventory.private.json"
    payload = inventory.read_bytes()
    if mutation == "replace":
        inventory.unlink()
        inventory.write_bytes(payload)
        inventory.chmod(0o600)
    elif mutation == "symlink":
        outside = tmp_path / "outside-inventory.json"
        inventory.rename(outside)
        inventory.symlink_to(outside)
    elif mutation == "hardlink":
        os.link(inventory, config.attempt_root / "inventory-alias.private.json")
    else:
        inventory.chmod(0o644)

    with pytest.raises(PreflightError, match="INVENTORY_NOT_FROZEN|ATTEMPT_FILE_INVALID"):
        freeze_batch_manifest(config, expected_test_sheet_sha256=sheet_sha)


def test_freeze_rechecks_inventory_inode_after_selector_to_close_toctou(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, sheet_sha = _ready_frozen_attempt(tmp_path)
    inventory = config.attempt_root / "inventory.private.json"
    original_selector = prepare_module.select_calibration_batch

    def replacing_selector(*args: object, **kwargs: object):
        payload = inventory.read_bytes()
        inventory.unlink()
        inventory.write_bytes(payload)
        inventory.chmod(0o600)
        return original_selector(*args, **kwargs)

    monkeypatch.setattr(prepare_module, "select_calibration_batch", replacing_selector)

    with pytest.raises(PreflightError, match="INVENTORY_CHANGED"):
        freeze_batch_manifest(config, expected_test_sheet_sha256=sheet_sha)

    assert not (config.attempt_root / "batch-manifest.private.json").exists()


def test_freeze_rechecks_complete_marker_inode_after_selector_to_close_toctou(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, sheet_sha = _ready_frozen_attempt(tmp_path)
    complete = config.attempt_root / "preflight.complete.private.json"
    original_selector = prepare_module.select_calibration_batch

    def replacing_selector(*args: object, **kwargs: object):
        payload = complete.read_bytes()
        complete.unlink()
        complete.write_bytes(payload)
        complete.chmod(0o600)
        return original_selector(*args, **kwargs)

    monkeypatch.setattr(prepare_module, "select_calibration_batch", replacing_selector)

    with pytest.raises(PreflightError, match="MARKER_CHANGED"):
        freeze_batch_manifest(config, expected_test_sheet_sha256=sheet_sha)

    assert not (config.attempt_root / "batch-manifest.private.json").exists()


def test_freeze_rejects_attempt_root_owner_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, sheet_sha = _ready_frozen_attempt(tmp_path)
    monkeypatch.setattr(prepare_module, "_expected_uid", lambda: os.geteuid() + 1, raising=False)

    with pytest.raises(PreflightError, match="ATTEMPT_ROOT_SECURITY_INVALID"):
        freeze_batch_manifest(config, expected_test_sheet_sha256=sheet_sha)


def test_import_rejects_attempt_root_inode_swap_before_database_write(tmp_path: Path) -> None:
    config, sheet_sha, manifest_sha = _ready_import_attempt(tmp_path)
    original = tmp_path / "original-import-attempt"
    config.attempt_root.rename(original)
    shutil.copytree(original, config.attempt_root)
    config.attempt_root.chmod(0o700)
    db, _ = _clients()

    with pytest.raises(PreflightError, match="ATTEMPT_ROOT_IDENTITY_MISMATCH"):
        import_batch(
            config,
            db=db,
            expected_test_sheet_sha256=sheet_sha,
            expected_manifest_raw_sha256=manifest_sha,
            apply=True,
        )

    assert db.write_calls == []


@pytest.mark.parametrize("mutation", ("replace", "symlink", "hardlink", "mode"))
def test_import_rejects_manifest_identity_and_private_file_mutations_before_write(
    tmp_path: Path, mutation: str
) -> None:
    config, sheet_sha, manifest_sha = _ready_import_attempt(tmp_path)
    manifest = config.attempt_root / "batch-manifest.private.json"
    payload = manifest.read_bytes()
    if mutation == "replace":
        manifest.unlink()
        manifest.write_bytes(payload)
        manifest.chmod(0o600)
    elif mutation == "symlink":
        outside = tmp_path / "outside-manifest.json"
        manifest.rename(outside)
        manifest.symlink_to(outside)
    elif mutation == "hardlink":
        os.link(manifest, config.attempt_root / "manifest-alias.private.json")
    else:
        manifest.chmod(0o644)
    db, _ = _clients()

    with pytest.raises(
        PreflightError,
        match="MANIFEST_NOT_COMPLETE|MANIFEST_RAW_PIN_MISMATCH|ATTEMPT_FILE_INVALID",
    ):
        import_batch(
            config,
            db=db,
            expected_test_sheet_sha256=sheet_sha,
            expected_manifest_raw_sha256=manifest_sha,
            apply=True,
        )

    assert db.write_calls == []


def test_import_rejects_complete_marker_same_bytes_inode_replacement_before_write(
    tmp_path: Path,
) -> None:
    config, sheet_sha, manifest_sha = _ready_import_attempt(tmp_path)
    complete = config.attempt_root / "manifest.complete.private.json"
    payload = complete.read_bytes()
    complete.unlink()
    complete.write_bytes(payload)
    complete.chmod(0o600)
    db, _ = _clients()

    with pytest.raises(PreflightError, match="MANIFEST_NOT_COMPLETE"):
        import_batch(
            config,
            db=db,
            expected_test_sheet_sha256=sheet_sha,
            expected_manifest_raw_sha256=manifest_sha,
            apply=True,
        )

    assert db.write_calls == []


def test_import_rechecks_complete_marker_after_owner_read_before_write(tmp_path: Path) -> None:
    config, sheet_sha, manifest_sha = _ready_import_attempt(tmp_path)
    complete = config.attempt_root / "manifest.complete.private.json"
    db, _ = _clients()
    original_read = db.read

    def replacing_read(operation: str, params: dict[str, object]) -> list[dict[str, object]]:
        rows = original_read(operation, params)
        payload = complete.read_bytes()
        complete.unlink()
        complete.write_bytes(payload)
        complete.chmod(0o600)
        return rows

    db.read = replacing_read  # type: ignore[method-assign]

    with pytest.raises(PreflightError, match="MARKER_CHANGED"):
        import_batch(
            config,
            db=db,
            expected_test_sheet_sha256=sheet_sha,
            expected_manifest_raw_sha256=manifest_sha,
            apply=True,
        )

    assert db.write_calls == []


def test_apply_requires_exact_sheet_and_manifest_raw_sha_before_one_rpc(tmp_path: Path) -> None:
    config = _config(tmp_path, frozen_sheet=True)
    db, r2 = _clients()
    run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)
    sheet_sha = hashlib.sha256(config.test_sheet_path.read_bytes()).hexdigest()
    freeze_batch_manifest(config, expected_test_sheet_sha256=sheet_sha)
    manifest_sha = hashlib.sha256(
        (config.attempt_root / "batch-manifest.private.json").read_bytes()
    ).hexdigest()

    with pytest.raises(PreflightError, match="TEST_SHEET_PIN_MISMATCH"):
        import_batch(
            config,
            db=db,
            expected_test_sheet_sha256="0" * 64,
            expected_manifest_raw_sha256=manifest_sha,
            apply=True,
        )
    assert db.write_calls == []

    result = import_batch(
        config,
        db=db,
        expected_test_sheet_sha256=sheet_sha,
        expected_manifest_raw_sha256=manifest_sha,
        apply=True,
    )

    assert result["status"] == "prepared"
    assert len(db.write_calls) == 1
    operation, params = db.write_calls[0]
    assert operation == "fn_create_gme_negative_audit_batch"
    assert params["p_owner_id"] == OWNER_ID
    assert params["p_manifest"]["manifest_sha256"]


@pytest.mark.parametrize("apply", (False, None))
def test_import_is_impossible_without_literal_apply_true(tmp_path: Path, apply: object) -> None:
    config = _config(tmp_path, frozen_sheet=True)
    db, _ = _clients()

    with pytest.raises(PreflightError, match="APPLY_REQUIRED"):
        import_batch(
            config,
            db=db,
            expected_test_sheet_sha256="0" * 64,
            expected_manifest_raw_sha256="0" * 64,
            apply=apply,
        )

    assert db.read_calls == db.write_calls == []


def test_media_probe_hashes_actual_bytes_decodes_video_and_releases_temp_resources(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "fixture.mp4"
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 4.0, (32, 24)
    )
    assert writer.isOpened()
    try:
        for value in (0, 64, 128, 255):
            writer.write(np.full((24, 32, 3), value, dtype=np.uint8))
    finally:
        writer.release()
    payload = video_path.read_bytes()

    media_sha, media_dhash = _probe_media_bytes(payload)

    assert media_sha == hashlib.sha256(payload).hexdigest()
    assert len(media_dhash) == 16
    assert not list(tmp_path.glob("*.probe-*"))
    with pytest.raises(PreflightError, match="MEDIA_DECODE_FAILED"):
        _probe_media_bytes(b"not-a-video")


def test_help_and_empty_cli_do_not_construct_clients_or_write(tmp_path: Path) -> None:
    calls: list[str] = []

    assert main([], db_factory=lambda: calls.append("db"), r2_factory=lambda: calls.append("r2")) == 0
    assert main(["--help"], db_factory=lambda: calls.append("db"), r2_factory=lambda: calls.append("r2")) == 0
    assert calls == []
    assert list(tmp_path.iterdir()) == []


def test_direct_script_help_works_outside_repo_import_context(tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "scripts" / "prepare_gme_negative_audit_batch.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "preflight" in completed.stdout
    assert "freeze" in completed.stdout
    assert "import" in completed.stdout


def test_direct_script_no_args_is_help_without_traceback_or_client_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = Path(__file__).parents[1] / "scripts" / "prepare_gme_negative_audit_batch.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "preflight" in completed.stdout
    assert "Traceback" not in completed.stderr

    calls: list[str] = []
    monkeypatch.setattr(sys, "argv", [str(script)])
    assert main(None, db_factory=lambda: calls.append("db"), r2_factory=lambda: calls.append("r2")) == 0
    assert calls == []


def test_cli_preflight_requires_explicit_command_and_uses_only_injected_read_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    db, r2 = _clients()
    monkeypatch.setenv("DEV_USER_ID", OWNER_ID)
    monkeypatch.setattr(
        "scripts.prepare_gme_negative_audit_batch._probe_media_bytes",
        lambda payload: (hashlib.sha256(payload).hexdigest(), _fake_probe(payload)),
    )
    protected_paths = []
    for pin in config.protected_manifests:
        protected_paths.extend(
            [
                "--protected-manifest",
                f"{pin.role}={pin.path}",
                "--protected-manifest-sha256",
                f"{pin.role}={pin.raw_sha256}",
            ]
        )

    exit_code = main(
        [
            "preflight",
            "--attempt-root",
            str(config.attempt_root),
            "--training-manifest",
            str(config.training_manifest.path),
            "--training-manifest-sha256",
            config.training_manifest.raw_sha256,
            *protected_paths,
            "--test-sheet",
            str(config.test_sheet_path),
            "--r2-bucket",
            config.r2_bucket,
        ],
        db_factory=lambda: db,
        r2_factory=lambda: r2,
    )

    assert exit_code == 0
    assert db.write_calls == []
    assert r2.write_calls == []
    assert (config.attempt_root / "preflight.complete.private.json").is_file()


def test_cli_import_without_apply_never_constructs_db_or_writes(tmp_path: Path) -> None:
    calls: list[str] = []

    with pytest.raises(SystemExit):
        main(
            [
                "import",
                "--attempt-root",
                str(tmp_path / "attempt"),
                "--test-sheet",
                str(tmp_path / "TEST-SHEET.md"),
                "--expected-test-sheet-sha256",
                "0" * 64,
                "--expected-manifest-raw-sha256",
                "0" * 64,
            ],
            db_factory=lambda: calls.append("db"),
            r2_factory=lambda: calls.append("r2"),
        )

    assert calls == []


def test_live_read_adapter_keeps_known_visible_gme_negatives_in_both_source_populations() -> None:
    adapter = _SupabaseAuditDb(object())
    plain = _row(1)
    control_negative = _row(2, control=True)
    control_negative["current_detected"] = False
    adapter._source_cache = [plain, control_negative]

    negatives = adapter.read(
        "negative_candidates", {"cutoff": CUTOFF, "detector_identity": DETECTOR_IDENTITY}
    )
    controls = adapter.read(
        "positive_controls", {"cutoff": CUTOFF, "detector_identity": DETECTOR_IDENTITY}
    )

    assert negatives == [plain, control_negative]
    assert controls == [control_negative]


def test_live_adapter_hashes_human_gt_from_database_canonical_json_not_python_float() -> None:
    class Response:
        data = '{"bbox":{"x":0.10},"visibility":"visible"}'

    class Rpc:
        def execute(self) -> Response:
            return Response()

    class Client:
        def rpc(self, operation: str, params: dict[str, object]) -> Rpc:
            assert operation == "fn_gme_negative_audit_canonical_json"
            assert params == {"p_value": {"bbox": {"x": 0.1}, "visibility": "visible"}}
            return Rpc()

    adapter = _SupabaseAuditDb(Client())

    digest = adapter._canonical_gt_digest(
        {"bbox": {"x": 0.1}, "visibility": "visible"}
    )

    assert digest == hashlib.sha256(Response.data.encode()).hexdigest()


def test_database_timestamp_is_canonicalized_from_explicit_offset() -> None:
    assert _canonicalize_database_timestamp("2026-08-15T09:00:00+09:00") == (
        "2026-08-15T00:00:00Z"
    )


def test_errors_and_safe_availability_do_not_expose_source_identity(tmp_path: Path) -> None:
    config = _config(tmp_path)
    db, r2 = _clients(negative_count=120)
    secret_key = str(db.negatives[0]["r2_key"])
    del r2.payload_by_key[secret_key]

    result = run_preflight(config, db=db, r2=r2, media_probe=_fake_probe)

    assert secret_key not in json.dumps(result)
    assert secret_key not in (config.attempt_root / "availability.private.json").read_text()
    assert result["status"] == "GME_NEGATIVE_AUDIT_SHORTAGE"
