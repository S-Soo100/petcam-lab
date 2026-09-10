from __future__ import annotations

import json
import hashlib
import shutil
import stat
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import scripts.yolo26n_v27_c500g.inventory as inventory_module
from scripts.yolo26n_v27_c500g.inventory import (
    DB_SELECT_COLUMNS,
    collect_inventory,
    inventory_public_summary,
)


TEST_SHEET_SHA256 = "a" * 64


def _manifest(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _camera_digest(camera_key: str) -> str:
    return hashlib.sha256(f"camera:{camera_key}".encode("utf-8")).hexdigest()


def _week_slots(start_night: date = date(2026, 8, 20)) -> list[dict[str, object]]:
    kst = ZoneInfo("Asia/Seoul")
    slots: list[dict[str, object]] = []
    for camera in ("cam01", "cam02", "cam03"):
        for day_offset in range(7):
            night = start_night + timedelta(days=day_offset)
            start = datetime.combine(night, datetime.min.time(), tzinfo=kst) + timedelta(
                hours=20
            )
            for slot_index in range(24):
                scheduled = start + timedelta(minutes=30 * slot_index)
                slots.append(
                    {
                        "anonymous_camera_digest": _camera_digest(camera),
                        "night_date": night.isoformat(),
                        "scheduled_start_utc": scheduled.astimezone(UTC)
                        .isoformat()
                        .replace("+00:00", "Z"),
                    }
                )
    return slots


def _schedule_digest(slots: list[dict[str, object]]) -> str:
    payload = {
        "schema": "yolo26n-v27-c500g-expected-slots-v1",
        "timezone": "Asia/Seoul",
        "duration_sec": 1800,
        "slots": sorted(
            slots,
            key=lambda item: (
                item["anonymous_camera_digest"],
                item["night_date"],
                item["scheduled_start_utc"],
            ),
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _expected_slots(fake_bundle) -> dict[str, object]:
    del fake_bundle
    return _schedule_ledger(_week_slots())


def _schedule_ledger(slots: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema": "yolo26n-v27-c500g-expected-slots-v1",
        "test_sheet_sha256": TEST_SHEET_SHA256,
        "schedule_sha256": _schedule_digest(slots),
        "timezone": "Asia/Seoul",
        "duration_sec": 1800,
        "slots": slots,
    }


def populate_week(fake_bundle, fake_r2, fake_db) -> None:
    """fake_bundle 하나짜리 fixture 를 3카메라 × 7밤 × 24슬롯(504) 합성 트리 + R2/DB 로 확장 (test_cli 도 재사용)."""
    from backend.rap_c500g_repository import manifest_to_row

    first_manifest = _manifest(fake_bundle.manifest)
    first_video = first_manifest["artifacts"][0]
    fake_r2.objects[first_video["r2_key"]]["Metadata"] = {
        "sha256": first_video["sha256"],
        "bundle-id": first_manifest["bundle_id"],
        "camera-key": first_manifest["camera_key"],
    }

    kst = ZoneInfo("Asia/Seoul")
    for camera in ("cam01", "cam02", "cam03"):
        for day_offset in range(7):
            night = date(2026, 8, 20) + timedelta(days=day_offset)
            start = datetime.combine(night, datetime.min.time(), tzinfo=kst) + timedelta(
                hours=20
            )
            for slot_index in range(24):
                if camera == "cam01" and day_offset == 0 and slot_index == 0:
                    continue
                scheduled = start + timedelta(minutes=30 * slot_index)
                scheduled_utc = scheduled.astimezone(UTC).isoformat()
                segment = scheduled.strftime("%Y%m%dT%H%M%S%z")
                relative = f"{camera}/night={night.isoformat()}/{segment}"
                bundle_dir = fake_bundle.root / relative
                bundle_dir.mkdir(parents=True)
                video = bundle_dir / "video.mp4"
                video_bytes = f"synthetic-{camera}-{night}-{slot_index}".encode("ascii")
                video.write_bytes(video_bytes)
                video_sha = hashlib.sha256(video_bytes).hexdigest()
                bundle_id = "rap-" + hashlib.sha256(relative.encode("ascii")).hexdigest()[:32]

                def artifact(name: str, content: bytes, content_type: str):
                    return {
                        "name": name,
                        "size_bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "content_type": content_type,
                        "r2_key": f"{relative}/{name}",
                    }

                artifacts = [
                    {
                        "name": "video.mp4",
                        "size_bytes": len(video_bytes),
                        "sha256": video_sha,
                        "content_type": "video/mp4",
                        "r2_key": f"{relative}/video.mp4",
                    },
                    artifact("thumbnail.jpg", b"thumbnail", "image/jpeg"),
                    artifact(
                        "ffmpeg.sanitized.log",
                        b"safe-log",
                        "text/plain; charset=utf-8",
                    ),
                ]
                manifest = {
                    "schema": "rap-c500g-bundle/v1",
                    "bundle_id": bundle_id,
                    "mode": "production",
                    "camera_key": camera,
                    "test_run_id": None,
                    "night_date": night.isoformat(),
                    "scheduled_start_utc": scheduled_utc,
                    "actual_start_utc": scheduled_utc,
                    "partial": False,
                    "relative_bundle_path": relative,
                    "media": {
                        "duration_sec": 1800.0,
                        "codec": "hevc",
                        "width": 2880,
                        "height": 1620,
                        "fps": 15.0,
                    },
                    "capture": {"ffmpeg_exit_code": 0, "verified": True},
                    "artifacts": artifacts,
                    "manifest_r2_key": f"{relative}/manifest.json",
                    "upload_status": "uploaded",
                    "r2_verified": True,
                }
                _write_manifest(bundle_dir / "manifest.json", manifest)
                fake_db.rows.append(manifest_to_row(manifest))
                for item in artifacts:
                    fake_r2.objects[item["r2_key"]] = {
                        "ContentLength": item["size_bytes"],
                        "Metadata": {
                            "sha256": item["sha256"],
                            "bundle-id": bundle_id,
                            "camera-key": camera,
                        },
                    }

    original_head = fake_r2.head_object

    def head(**kwargs: object):
        result = original_head(**kwargs)
        key = str(kwargs["Key"])
        result["Metadata"] = dict(fake_r2.objects[key]["Metadata"])
        return result

    fake_r2.head_object = head


@pytest.fixture(autouse=True)
def production_r2_metadata(fake_bundle, fake_r2, fake_db):
    populate_week(fake_bundle, fake_r2, fake_db)


def test_inventory_requires_approved_expected_slot_ledger(
    fake_bundle, fake_r2, fake_db
):
    with pytest.raises(TypeError, match="expected_slots"):
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
        )


def test_inventory_rejects_duplicate_and_unknown_expected_slots(
    fake_bundle, fake_r2, fake_db
):
    ledger = _expected_slots(fake_bundle)
    ledger["slots"][-1] = dict(ledger["slots"][0])
    with pytest.raises(ValueError, match="duplicate"):
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=ledger,
        )

    physical_duplicate = _expected_slots(fake_bundle)
    duplicate_with_wrong_night = dict(physical_duplicate["slots"][0])
    duplicate_with_wrong_night["night_date"] = "2026-08-21"
    physical_duplicate["slots"][-1] = duplicate_with_wrong_night
    with pytest.raises(ValueError, match="duplicate"):
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=physical_duplicate,
        )

    unknown = _expected_slots(fake_bundle)
    unknown["unexpected"] = True
    with pytest.raises(ValueError, match="unknown"):
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=unknown,
        )


def test_inventory_counts_missing_and_extra_slots_against_approved_schedule(
    fake_bundle, fake_r2, fake_db
):
    # 진짜 결손(녹화 자체가 없었던 슬롯) = 로컬·DB·R2 어디에도 없음. DB 행만 남아 있으면 그건 정체성 불일치다.
    _forget_bundle(fake_bundle, fake_r2, fake_db)
    missing = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
        expected_slots=_expected_slots(fake_bundle),
    )
    assert missing["expected_slot_count"] == 504
    assert missing["missing_slot_count"] == 1
    # inventory v1.1 (2026-09-10 addendum): 예정 슬롯 결손은 정체성 불일치가 아니라 schedule gap 으로 보고한다.
    assert missing["status"] == "V27_SOURCE_INVENTORY_READY"
    assert missing["schedule_gap_count"] == 1
    assert missing["mismatch_count"] == 0


def test_inventory_reports_actual_slot_outside_approved_schedule(
    fake_bundle, fake_r2, fake_db
):
    payload = _manifest(fake_bundle.manifest)
    extra_relative = "cam01/night=2026-08-20/extra-off-grid"
    extra_dir = fake_bundle.root / extra_relative
    extra_dir.mkdir()
    shutil.copy2(fake_bundle.video, extra_dir / "video.mp4")
    payload["bundle_id"] = "rap-extra-off-grid"
    payload["relative_bundle_path"] = extra_relative
    payload["scheduled_start_utc"] = "2026-08-20T11:15:00Z"
    payload["actual_start_utc"] = "2026-08-20T11:15:00Z"
    payload["manifest_r2_key"] = f"{extra_relative}/manifest.json"
    for artifact in payload["artifacts"]:
        artifact["r2_key"] = f"{extra_relative}/{artifact['name']}"
    _write_manifest(extra_dir / "manifest.json", payload)
    _register_bundle(payload, fake_r2, fake_db)  # 레거시 번들도 R2·DB 에는 정상 존재한다

    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
        expected_slots=_expected_slots(fake_bundle),
    )

    # inventory v1.1: 그리드 밖 번들은 unscheduled(train 전용 소스)로 보고하고 정체성 불일치로 다루지 않는다.
    assert result["status"] == "V27_SOURCE_INVENTORY_READY"
    assert result["unscheduled_bundle_count"] == 1
    assert not any("unexpected_actual_slot" in item["reasons"] for item in result["mismatches"])
    flagged = [r for r in result["records"] if r["source_ref"] == extra_relative]
    assert flagged and flagged[0]["scheduled_slot"] is False and flagged[0]["night_date"] == "2026-08-20"


def test_inventory_treats_equivalent_utc_spellings_as_the_same_slot(
    fake_bundle, fake_r2, fake_db
):
    ledger = _expected_slots(fake_bundle)
    scheduled = ledger["slots"][0]["scheduled_start_utc"]
    assert scheduled.endswith("Z")
    ledger["slots"][0]["scheduled_start_utc"] = scheduled.removesuffix("Z") + "+00:00"

    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
        expected_slots=ledger,
    )

    assert result["status"] == "V27_SOURCE_INVENTORY_READY"


def test_inventory_accepts_uploader_metadata_and_checks_r2_identity(
    fake_bundle, fake_r2, fake_db
):
    original_head = fake_r2.head_object
    ready = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
        expected_slots=_expected_slots(fake_bundle),
    )
    assert ready["status"] == "V27_SOURCE_INVENTORY_READY"

    def wrong_camera_head(**kwargs: object):
        result = original_head(**kwargs)
        if str(kwargs["Key"]) == _manifest(fake_bundle.manifest)["artifacts"][0]["r2_key"]:
            result["Metadata"]["camera-key"] = "different-camera"
        return result

    fake_r2.head_object = wrong_camera_head
    mismatch = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
        expected_slots=_expected_slots(fake_bundle),
    )
    assert mismatch["status"] == "V27_SOURCE_INVENTORY_MISMATCH"
    assert mismatch["mismatch_count"] == 1


def test_inventory_accepts_boto_head_transport_envelope(
    fake_bundle, fake_r2, fake_db
):
    original_head = fake_r2.head_object

    def boto_head(**kwargs: object):
        return {
            **original_head(**kwargs),
            "AcceptRanges": "bytes",
            "ResponseMetadata": {
                "RequestId": "synthetic",
                "HTTPStatusCode": 200,
                "HTTPHeaders": {},
                "RetryAttempts": 0,
            },
            "x-provider-transport-extension": "ignored",
        }

    fake_r2.head_object = boto_head
    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
        expected_slots=_expected_slots(fake_bundle),
    )
    assert result["status"] == "V27_SOURCE_INVENTORY_READY"


def test_inventory_schedule_rejects_missing_digest_and_non_week_contract(
    fake_bundle, fake_r2, fake_db
):
    missing_digest = _expected_slots(fake_bundle)
    del missing_digest["schedule_sha256"]
    with pytest.raises(ValueError, match="schedule_sha256"):
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=missing_digest,
        )


@pytest.mark.parametrize(
    ("field", "bad_value", "message"),
    [
        ("night_date", "2026-02-30", "calendar date"),
        ("scheduled_start_utc", "2026-02-30T11:00:00Z", "UTC datetime"),
    ],
)
def test_inventory_schedule_rejects_impossible_calendar_values(
    fake_bundle, fake_r2, fake_db, field, bad_value, message
):
    ledger = _expected_slots(fake_bundle)
    ledger["slots"][0][field] = bad_value
    ledger["schedule_sha256"] = _schedule_digest(ledger["slots"])

    with pytest.raises(ValueError, match=message):
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=ledger,
        )


def test_inventory_schedule_rejects_nonconsecutive_nights_off_grid_and_digest_drift(
    fake_bundle, fake_r2, fake_db
):
    base = [slot for slot in _week_slots() if slot["night_date"] != "2026-08-26"]
    replacement = [
        slot
        for slot in _week_slots(date(2026, 8, 28))
        if slot["night_date"] == "2026-08-28"
    ]
    nonconsecutive = _schedule_ledger(base + replacement)
    with pytest.raises(ValueError, match="consecutive"):
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=nonconsecutive,
        )

    off_grid = _expected_slots(fake_bundle)
    parsed = datetime.fromisoformat(
        off_grid["slots"][0]["scheduled_start_utc"].replace("Z", "+00:00")
    ) + timedelta(minutes=1)
    off_grid["slots"][0]["scheduled_start_utc"] = parsed.isoformat().replace(
        "+00:00", "Z"
    )
    off_grid["schedule_sha256"] = _schedule_digest(off_grid["slots"])
    with pytest.raises(ValueError, match="half-hour"):
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=off_grid,
        )

    drift = _expected_slots(fake_bundle)
    drift["schedule_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="schedule_sha256 mismatch"):
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=drift,
        )

    one_slot = _expected_slots(fake_bundle)
    one_slot["slots"] = one_slot["slots"][:1]
    one_slot["schedule_sha256"] = _schedule_digest(one_slot["slots"])
    with pytest.raises(ValueError, match="72"):  # v1.1: 밤당 3카메라 × 24 = 72 슬롯의 배수여야 한다
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=one_slot,
        )


# ── inventory v1.1 (2026-09-10 addendum) ─────────────────────────────

def _forget_bundle(fake_bundle, fake_r2, fake_db) -> None:
    """fake_bundle 의 대표 번들을 로컬·R2·DB 세 계층에서 모두 제거 → 순수 스케줄 결손."""
    payload = _manifest(fake_bundle.manifest)
    fake_bundle.manifest.unlink()
    for artifact in payload["artifacts"]:
        fake_r2.objects.pop(artifact["r2_key"], None)
    fake_db.rows = [row for row in fake_db.rows if row["bundle_id"] != payload["bundle_id"]]


def _register_bundle(payload: dict[str, object], fake_r2, fake_db) -> None:
    from backend.rap_c500g_repository import manifest_to_row

    for artifact in payload["artifacts"]:
        metadata = {"sha256": artifact["sha256"]}
        if artifact["name"] == "video.mp4":
            metadata.update({"bundle-id": payload["bundle_id"], "camera-key": payload["camera_key"]})
        fake_r2.objects[artifact["r2_key"]] = {"ContentLength": artifact["size_bytes"], "Metadata": metadata}
    fake_db.rows.append(manifest_to_row(payload))


def _rewrite_manifest(path: Path, **changes: object) -> dict[str, object]:
    payload = _manifest(path)
    for key, value in changes.items():
        if key == "media":
            payload["media"] = {**payload["media"], **value}
        else:
            payload[key] = value
    _write_manifest(path, payload)
    return payload


def _resync_db(fake_bundle, fake_db) -> None:
    from backend.rap_c500g_repository import manifest_to_row

    fake_db.rows = [manifest_to_row(_manifest(p)) for p in sorted(fake_bundle.root.rglob("manifest.json"))]


def test_inventory_v11_accepts_two_night_schedule_and_reports_unscheduled_bundles(fake_bundle, fake_r2, fake_db):
    two_nights = _schedule_ledger([s for s in _week_slots() if s["night_date"] in ("2026-08-20", "2026-08-21")])
    result = collect_inventory(fake_bundle.root, fake_r2, fake_db, test_sheet_sha256=TEST_SHEET_SHA256, expected_slots=two_nights)
    assert result["status"] == "V27_SOURCE_INVENTORY_READY"
    assert result["expected_slot_count"] == 144
    assert result["unscheduled_bundle_count"] == 360
    assert result["complete_camera_night_count"] == 6
    assert sum(1 for r in result["records"] if r["scheduled_slot"]) == 144


def test_inventory_v11_late_start_or_short_slot_is_incomplete_not_mismatch(fake_bundle, fake_r2, fake_db):
    late = fake_bundle.root / "cam02/night=2026-08-21/20260821T203000+0900/manifest.json"
    _rewrite_manifest(late, actual_start_utc="2026-08-21T11:45:00+00:00", partial=True, media={"duration_sec": 900.0})
    fine = fake_bundle.root / "cam03/night=2026-08-22/20260822T210000+0900/manifest.json"
    _rewrite_manifest(fine, actual_start_utc="2026-08-22T12:00:05+00:00", partial=True, media={"duration_sec": 1775.0})
    _resync_db(fake_bundle, fake_db)
    result = collect_inventory(fake_bundle.root, fake_r2, fake_db, test_sheet_sha256=TEST_SHEET_SHA256, expected_slots=_expected_slots(fake_bundle))
    assert result["status"] == "V27_SOURCE_INVENTORY_READY"
    assert result["mismatch_count"] == 0
    assert result["incomplete_slot_count"] == 1
    assert result["complete_camera_night_count"] == 20  # cam02/08-21 만 불완비
    by_ref = {r["source_ref"]: r for r in result["records"]}
    late_rec = by_ref["cam02/night=2026-08-21/20260821T203000+0900"]
    fine_rec = by_ref["cam03/night=2026-08-22/20260822T210000+0900"]
    assert late_rec["complete_slot"] is False and late_rec["start_offset_sec"] == 900.0 and late_rec["partial"] is True
    assert fine_rec["complete_slot"] is True and fine_rec["start_offset_sec"] == 5.0


def test_build_expected_slots_matches_canonical_test_ledger():
    from scripts.yolo26n_v27_c500g.inventory import build_expected_slots

    nights = [(date(2026, 8, 20) + timedelta(days=i)).isoformat() for i in range(7)]
    built = build_expected_slots(["cam01", "cam02", "cam03"], nights, test_sheet_sha256=TEST_SHEET_SHA256)
    reference = _schedule_ledger(_week_slots())
    assert built["schedule_sha256"] == reference["schedule_sha256"]
    assert built["schema"] == reference["schema"] and built["timezone"] == "Asia/Seoul" and built["duration_sec"] == 1800
    assert sorted(built["slots"], key=lambda s: (s["anonymous_camera_digest"], s["night_date"], s["scheduled_start_utc"])) == sorted(
        reference["slots"], key=lambda s: (s["anonymous_camera_digest"], s["night_date"], s["scheduled_start_utc"]))
    assert not any("cam0" in s["anonymous_camera_digest"] for s in built["slots"])  # 카메라 키는 digest 로만
    with pytest.raises(ValueError, match="consecutive"):
        build_expected_slots(["cam01", "cam02", "cam03"], ["2026-08-20", "2026-08-22"], test_sheet_sha256=TEST_SHEET_SHA256)


def test_inventory_v11_public_summary_carries_gap_and_unscheduled_counts(fake_bundle, fake_r2, fake_db):
    _forget_bundle(fake_bundle, fake_r2, fake_db)
    result = collect_inventory(fake_bundle.root, fake_r2, fake_db, test_sheet_sha256=TEST_SHEET_SHA256, expected_slots=_expected_slots(fake_bundle))
    summary = inventory_public_summary(result)
    assert summary["schedule_gap_count"] == 1
    assert summary["unscheduled_bundle_count"] == 0
    assert summary["incomplete_slot_count"] == 0


def test_inventory_counts_only_camera_nights_with_all_24_complete_slots(
    fake_bundle, fake_r2, fake_db
):
    fake_bundle.manifest.unlink()
    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
        expected_slots=_expected_slots(fake_bundle),
    )
    assert result["complete_camera_night_count"] == 20


def test_inventory_reports_orphan_r2_video_but_ignores_non_video_artifact(
    fake_bundle, fake_r2, fake_db
):
    fake_r2.objects["orphan/source/video.mp4"] = {
        "ContentLength": 10,
        "Metadata": {
            "sha256": "c" * 64,
            "bundle-id": "rap-orphan",
            "camera-key": "cam-orphan",
        },
    }
    fake_r2.objects["orphan/source/thumbnail.jpg"] = {
        "ContentLength": 10,
        "Metadata": {
            "sha256": "d" * 64,
            "bundle-id": "rap-orphan",
            "camera-key": "cam-orphan",
        },
    }

    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
        expected_slots=_expected_slots(fake_bundle),
    )

    reasons = [reason for item in result["mismatches"] for reason in item["reasons"]]
    assert reasons.count("orphan_r2_video") == 1


def test_inventory_hashes_video_with_bounded_streaming_buffer(
    monkeypatch, fake_bundle, fake_r2, fake_db
):
    calls: list[int] = []
    original = inventory_module.hashlib.file_digest

    def recording_file_digest(fileobj, digest, *, _bufsize=2**18):
        calls.append(_bufsize)
        return original(fileobj, digest, _bufsize=_bufsize)

    monkeypatch.setattr(inventory_module.hashlib, "file_digest", recording_file_digest)
    collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
        expected_slots=_expected_slots(fake_bundle),
    )

    assert calls
    assert max(calls) <= 1024 * 1024


def test_inventory_rejects_r2_head_without_uploader_identity_metadata(
    fake_bundle, fake_r2, fake_db
):
    original_head = fake_r2.head_object

    def incomplete_head(**kwargs: object):
        result = original_head(**kwargs)
        result["Metadata"] = {"sha256": result["Metadata"]["sha256"]}
        return result

    fake_r2.head_object = incomplete_head
    with pytest.raises(ValueError, match="missing required keys"):
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
        )


def test_inventory_rejects_symlinked_source_ancestor(
    tmp_path, fake_bundle, fake_r2, fake_db
):
    root = tmp_path / "symlinked-recordings"
    root.mkdir()
    (root / "cam01").symlink_to(fake_bundle.root / "cam01", target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        collect_inventory(
            root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
        )


def test_inventory_detects_opened_source_replacement_race(
    monkeypatch, fake_bundle, fake_r2, fake_db
):
    original_fstat = inventory_module.os.fstat
    regular_reads: dict[tuple[int, int], int] = {}

    def racing_fstat(fd: int):
        result = original_fstat(fd)
        if not stat.S_ISREG(result.st_mode):
            return result
        identity = (result.st_dev, result.st_ino)
        regular_reads[identity] = regular_reads.get(identity, 0) + 1
        if regular_reads[identity] != 2:
            return result
        return SimpleNamespace(
            st_mode=result.st_mode,
            st_dev=result.st_dev,
            st_ino=result.st_ino,
            st_size=result.st_size + 1,
            st_mtime_ns=result.st_mtime_ns,
        )

    monkeypatch.setattr(inventory_module.os, "fstat", racing_fstat)

    with pytest.raises(ValueError, match="changed during inventory"):
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
        )


def test_inventory_requires_local_r2_db_identity(fake_bundle, fake_r2, fake_db):
    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
    )

    assert result["status"] == "V27_SOURCE_INVENTORY_READY"
    assert result["storage_match_count"] == 504
    assert result["mismatch_count"] == 0
    assert result["missing_slot_count"] == 0
    assert len(result["records"]) == 504
    assert fake_r2.write_calls == []
    assert fake_db.write_calls == []


def test_inventory_reports_sha_mismatch_without_skipping(fake_bundle, fake_r2, fake_db):
    video_key = _manifest(fake_bundle.manifest)["artifacts"][0]["r2_key"]
    fake_r2.objects[video_key]["Metadata"]["sha256"] = "b" * 64

    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
    )

    assert result["status"] == "V27_SOURCE_INVENTORY_MISMATCH"
    assert result["mismatch_count"] == 1
    assert result["storage_match_count"] == 503
    assert len(result["records"]) == 504


@pytest.mark.parametrize(
    ("layer", "mutation"),
    [
        ("local", lambda bundle, _r2, _db: bundle.video.write_bytes(b"drift")),
        (
            "db",
            lambda _bundle, _r2, db: db.rows[0].__setitem__(
                "video_sha256", "b" * 64
            ),
        ),
        (
            "r2-size",
            lambda bundle, r2, _db: r2.objects[
                _manifest(bundle.manifest)["artifacts"][0]["r2_key"]
            ].__setitem__("ContentLength", 999),
        ),
    ],
)
def test_inventory_fails_closed_on_each_storage_identity_mismatch(
    fake_bundle, fake_r2, fake_db, layer, mutation
):
    mutation(fake_bundle, fake_r2, fake_db)

    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
    )

    assert result["status"] == "V27_SOURCE_INVENTORY_MISMATCH", layer
    assert result["mismatch_count"] == 1


def test_inventory_reports_missing_r2_video_as_missing_slot(fake_bundle, fake_r2, fake_db):
    video_key = _manifest(fake_bundle.manifest)["artifacts"][0]["r2_key"]
    del fake_r2.objects[video_key]

    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
    )

    assert result["status"] == "V27_SOURCE_INVENTORY_MISMATCH"
    assert result["missing_slot_count"] == 1
    assert result["mismatch_count"] == 1


def test_inventory_normalizes_boto_empty_list_response_and_keeps_writes_zero(
    fake_bundle, fake_r2, fake_db
):
    class EmptyR2:
        def __init__(self):
            self.write_calls: list[object] = []

        def list_objects_v2(self, **kwargs: object):
            assert kwargs == {}
            return {
                "IsTruncated": False,
                "Name": "synthetic-source-prefix",
                "Prefix": "recordings/",
                "MaxKeys": 1000,
                "KeyCount": 0,
                "ResponseMetadata": {
                    "HTTPStatusCode": 200,
                    "RetryAttempts": 0,
                },
            }

        def head_object(self, **kwargs: object):
            raise AssertionError(f"HEAD must not run for absent key: {kwargs}")

    reader = EmptyR2()
    result = collect_inventory(
        fake_bundle.root,
        reader,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
        expected_slots=_expected_slots(fake_bundle),
    )

    assert result["status"] == "V27_SOURCE_INVENTORY_MISMATCH"
    assert result["missing_slot_count"] == 504
    assert result["mismatch_count"] == 504
    assert all(
        "missing_r2_video" in mismatch["reasons"]
        for mismatch in result["mismatches"]
    )
    assert reader.write_calls == []
    assert fake_db.write_calls == []


def test_inventory_reads_every_r2_list_page(fake_bundle, fake_r2, fake_db):
    contents = fake_r2.list_objects_v2()["Contents"]
    video = next(item for item in contents if item["Key"].endswith("/video.mp4"))
    non_video = [item for item in contents if item is not video]

    class PaginatedR2:
        def __init__(self):
            self.calls: list[dict[str, object]] = []

        def list_objects_v2(self, **kwargs: object):
            self.calls.append(kwargs)
            if not kwargs:
                return {
                    "Contents": non_video,
                    "IsTruncated": True,
                    "NextContinuationToken": "page-2",
                }
            return {"Contents": [video], "IsTruncated": False}

        def head_object(self, **kwargs: object):
            return fake_r2.head_object(**kwargs)

    reader = PaginatedR2()

    result = collect_inventory(
        fake_bundle.root,
        reader,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
    )

    assert result["status"] == "V27_SOURCE_INVENTORY_READY"
    assert reader.calls == [{}, {"ContinuationToken": "page-2"}]


def test_inventory_reports_db_only_slot_without_hiding_it(fake_bundle, fake_r2, fake_db):
    missing_row = dict(fake_db.rows[0])
    missing_row["bundle_id"] = "rap-00000000000000000000000000000002"
    missing_row["camera_key"] = "cam02"
    missing_row["relative_bundle_path"] = "cam02/night=2026-08-20/missing"
    missing_row["video_r2_key"] = "cam02/night=2026-08-20/missing/video.mp4"
    missing_row["manifest_r2_key"] = "cam02/night=2026-08-20/missing/manifest.json"
    fake_db.rows.append(missing_row)

    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
        expected_slots=_expected_slots(fake_bundle),
    )

    assert result["expected_slot_count"] == 504
    assert result["actual_bundle_count"] == 504
    assert result["missing_slot_count"] == 0
    assert result["mismatch_count"] == 1


def test_inventory_audits_r2_identity_for_db_only_bundle(fake_bundle, fake_r2, fake_db):
    row = dict(fake_db.rows[0])
    row["bundle_id"] = "rap-00000000000000000000000000000002"
    row["camera_key"] = "cam02"
    row["relative_bundle_path"] = "cam02/night=2026-08-20/missing"
    row["video_r2_key"] = "cam02/night=2026-08-20/missing/video.mp4"
    row["manifest_r2_key"] = "cam02/night=2026-08-20/missing/manifest.json"
    fake_db.rows.append(row)
    fake_r2.objects[row["video_r2_key"]] = {
        "ContentLength": row["video_size_bytes"],
        "Metadata": {
            "sha256": row["video_sha256"],
            "bundle-id": row["bundle_id"],
            "camera-key": row["camera_key"],
        },
    }
    fake_r2.objects[row["video_r2_key"]]["Metadata"]["sha256"] = "b" * 64

    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
        expected_slots=_expected_slots(fake_bundle),
    )

    assert any(
        "r2_video_identity_mismatch" in mismatch["reasons"]
        for mismatch in result["mismatches"]
    )


def test_inventory_rejects_duplicate_local_bundle_id(fake_bundle, fake_r2, fake_db):
    duplicate_dir = fake_bundle.root / "cam02/night=2026-08-20/duplicate"
    duplicate_dir.mkdir(parents=True)
    shutil.copy2(fake_bundle.video, duplicate_dir / "video.mp4")
    duplicate = _manifest(fake_bundle.manifest)
    duplicate["relative_bundle_path"] = "cam02/night=2026-08-20/duplicate"
    duplicate["manifest_r2_key"] = (
        "cam02/night=2026-08-20/duplicate/manifest.json"
    )
    for artifact in duplicate["artifacts"]:
        artifact["r2_key"] = (
            f"cam02/night=2026-08-20/duplicate/{artifact['name']}"
        )
    _write_manifest(duplicate_dir / "manifest.json", duplicate)

    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
    )

    assert result["status"] == "V27_SOURCE_INVENTORY_MISMATCH"
    assert result["mismatch_count"] >= 1


def test_inventory_rejects_duplicate_db_bundle_id(fake_bundle, fake_r2, fake_db):
    fake_db.rows.append(dict(fake_db.rows[0]))

    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
    )

    assert result["status"] == "V27_SOURCE_INVENTORY_MISMATCH"
    assert result["mismatch_count"] == 1


@pytest.mark.parametrize(
    ("path", "key", "value"),
    [
        ((), "unexpected", True),
        (("media",), "unexpected", True),
        (("capture",), "unexpected", True),
        (("artifacts", 0), "unexpected", True),
    ],
)
def test_inventory_rejects_unknown_manifest_keys(
    fake_bundle, fake_r2, fake_db, path, key, value
):
    payload = _manifest(fake_bundle.manifest)
    target = payload
    for part in path:
        target = target[part]
    target[key] = value
    _write_manifest(fake_bundle.manifest, payload)

    with pytest.raises(ValueError, match="unknown"):
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
        )


@pytest.mark.parametrize("target", ["video", "manifest"])
def test_inventory_rejects_artifact_keys_outside_declared_bundle(
    fake_bundle, fake_r2, fake_db, target
):
    payload = _manifest(fake_bundle.manifest)
    if target == "video":
        payload["artifacts"][0]["r2_key"] = "another/bundle/video.mp4"
    else:
        payload["manifest_r2_key"] = "another/bundle/manifest.json"
    _write_manifest(fake_bundle.manifest, payload)

    with pytest.raises(ValueError, match="bundle path"):
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
        )


def test_inventory_v11_partial_flag_alone_does_not_break_completeness(fake_bundle, fake_r2, fake_db):
    # v1.1: `partial` 은 밀리초 차이로도 true 가 되는 플래그라 기록만 하고 판정에 쓰지 않는다.
    payload = _manifest(fake_bundle.manifest)
    payload["partial"] = True
    _write_manifest(fake_bundle.manifest, payload)
    _resync_db(fake_bundle, fake_db)
    result = collect_inventory(fake_bundle.root, fake_r2, fake_db, test_sheet_sha256=TEST_SHEET_SHA256, expected_slots=_expected_slots(fake_bundle))
    assert result["status"] == "V27_SOURCE_INVENTORY_READY"
    assert result["incomplete_slot_count"] == 0
    assert result["complete_camera_night_count"] == 21
    assert next(r for r in result["records"] if r["source_ref"] == payload["relative_bundle_path"])["partial"] is True


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("mode", "test"),
        ("upload_status", "pending"),
        ("r2_verified", False),
    ],
)
def test_inventory_marks_non_complete_manifest_as_mismatch(
    fake_bundle, fake_r2, fake_db, field, bad_value
):
    payload = _manifest(fake_bundle.manifest)
    payload[field] = bad_value
    _write_manifest(fake_bundle.manifest, payload)

    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
    )

    assert result["status"] == "V27_SOURCE_INVENTORY_MISMATCH"
    assert result["mismatch_count"] == 1
    assert result["complete_camera_night_count"] == 20


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("duration_sec", 1797.9),
        ("codec", "vp9"),
        ("width", 1920),
        ("height", 1080),
    ],
)
def test_inventory_marks_invalid_media_contract_as_mismatch(
    fake_bundle, fake_r2, fake_db, field, bad_value
):
    payload = _manifest(fake_bundle.manifest)
    payload["media"][field] = bad_value
    _write_manifest(fake_bundle.manifest, payload)

    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
    )

    assert result["status"] == "V27_SOURCE_INVENTORY_MISMATCH"
    assert result["mismatch_count"] == 1


def test_inventory_counts_recorded_decode_probe_failure_without_decoding(
    fake_bundle, fake_r2, fake_db
):
    payload = _manifest(fake_bundle.manifest)
    payload["capture"]["verified"] = False
    _write_manifest(fake_bundle.manifest, payload)

    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
    )

    assert result["decode_probe_failure_count"] == 1
    assert result["status"] == "V27_SOURCE_INVENTORY_MISMATCH"


def test_inventory_ignores_thumbnail_bytes_and_uses_existing_metadata_only(
    fake_bundle, fake_r2, fake_db
):
    fake_bundle.thumbnail.write_bytes(b"changed-but-not-opened-by-inventory")

    result = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
    )

    assert result["status"] == "V27_SOURCE_INVENTORY_READY"
    assert result["decode_probe_failure_count"] == 0


def test_inventory_uses_exact_read_only_db_projection(fake_bundle, fake_r2, fake_db):
    selected: list[str] = []
    original_select = fake_db.select

    def select(columns: str):
        selected.append(columns)
        return original_select(columns)

    fake_db.select = select

    collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
    )

    assert selected == [DB_SELECT_COLUMNS]
    assert fake_db.write_calls == []
    assert fake_r2.write_calls == []


def test_inventory_rejects_unknown_db_row_key(fake_bundle, fake_r2, fake_db):
    fake_db.rows[0]["secret_source_name"] = "must-not-pass"

    with pytest.raises(ValueError, match="unknown"):
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
        )


def test_inventory_rejects_invalid_test_sheet_sha_before_any_reader_call(
    fake_bundle, fake_r2, fake_db
):
    with pytest.raises(ValueError, match="test_sheet_sha256"):
        collect_inventory(
            fake_bundle.root,
            fake_r2,
            fake_db,
            test_sheet_sha256="A" * 64,
            expected_slots=_expected_slots(fake_bundle),
        )

    assert fake_db.write_calls == []
    assert fake_r2.write_calls == []


def test_inventory_public_summary_contains_only_seven_aggregate_fields(
    fake_bundle, fake_r2, fake_db
):
    inventory = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
    )

    summary = inventory_public_summary(inventory)

    assert summary == {
        "schema": "yolo26n-v27-c500g-inventory-summary-v1",
        "expected_slot_count": 504,
        "actual_bundle_count": 504,
        "complete_camera_night_count": 21,
        "missing_slot_count": 0,
        "schedule_gap_count": 0,  # v1.1 추가 3개 — aggregate 만
        "unscheduled_bundle_count": 0,
        "incomplete_slot_count": 0,
        "mismatch_count": 0,
        "decode_probe_failure_count": 0,
    }
    assert not any(
        word in json.dumps(summary, sort_keys=True)
        for word in ("bundle_id", "camera_key", "source_ref", "r2_key")
    )


def test_inventory_public_summary_rejects_unknown_private_inventory_key(
    fake_bundle, fake_r2, fake_db
):
    inventory = collect_inventory(
        fake_bundle.root,
        fake_r2,
        fake_db,
        test_sheet_sha256=TEST_SHEET_SHA256,
            expected_slots=_expected_slots(fake_bundle),
    )
    inventory["unexpected"] = "would otherwise be silently ignored"

    with pytest.raises(ValueError, match="unknown"):
        inventory_public_summary(inventory)
