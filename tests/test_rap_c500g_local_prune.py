from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend.rap_c500g_local_prune import (
    PruneSafetyError,
    build_prune_plan,
    capture_prune_root_guard,
    execute_prune,
)
from backend.rap_c500g_manifest import sha256_file
from backend.rap_c500g_pipeline_types import PipelineItem, PipelineState


KST = ZoneInfo("Asia/Seoul")


class MountInspector:
    def __init__(self, mount: Path, *, uuid: str = "volume-1") -> None:
        self.mount = mount
        self.uuid = uuid

    def is_mount(self, path: Path) -> bool:
        return path == self.mount

    def volume_uuid(self, path: Path) -> str:
        assert path == self.mount
        return self.uuid


class Heads:
    def __init__(self, values: dict[str, dict[str, object]]) -> None:
        self.values = values

    def head_object(self, key: str) -> dict[str, object] | None:
        return self.values.get(key)


class Repository:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.row = row

    def get_recording(self, bundle_id: str) -> dict[str, object] | None:
        assert bundle_id == "bundle-safe"
        return self.row


class Store:
    def __init__(self, item: PipelineItem, *, claim: str = "completed") -> None:
        self.item = item
        self.claim = claim

    def list_pipeline_items(self, **_kwargs) -> list[PipelineItem]:
        return [self.item]

    def read_capture_claim_statuses(self) -> dict[tuple[str, str], str]:
        return {(self.item.slot_start, self.item.camera_key): self.claim}


def make_bundle(tmp_path: Path, *, partial: bool = False, night: str = "2026-08-30"):
    mount = tmp_path / "RAP-C500G"
    root = mount / "RAP-c500g-recordings"
    bundle = root / "recordings" / "cam01" / f"night={night}" / "slot=20-00-00"
    bundle.mkdir(parents=True)
    artifacts = []
    for name, data in (("video.mp4", b"video"), ("thumbnail.jpg", b"jpg"), ("ffmpeg.sanitized.log", b"log")):
        path = bundle / name
        path.write_bytes(data)
        artifacts.append({
            "name": name,
            "size_bytes": len(data),
            "sha256": sha256_file(path),
            "r2_key": f"recordings/safe/{name}",
        })
    slot = f"{night}T20:00:00+09:00"
    manifest = {
        "schema": "rap-c500g-bundle/v1",
        "bundle_id": "bundle-safe",
        "mode": "production",
        "camera_key": "cam01",
        "night_date": night,
        "scheduled_start_utc": datetime.fromisoformat(slot).astimezone(ZoneInfo("UTC")).isoformat(),
        "partial": partial,
        "relative_bundle_path": bundle.relative_to(root).as_posix(),
        "artifacts": artifacts,
        "manifest_r2_key": "recordings/safe/manifest.json",
        "upload_status": "uploaded",
        "r2_verified": True,
        "uploaded_at": "2026-08-31T09:00:00+00:00",
    }
    manifest_path = bundle / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    heads = {
        str(item["r2_key"]): {
            "ContentLength": item["size_bytes"], "sha256": item["sha256"], "LastModified": 1
        }
        for item in artifacts
    }
    heads["recordings/safe/manifest.json"] = {
        "ContentLength": manifest_path.stat().st_size,
        "sha256": sha256_file(manifest_path),
        "LastModified": 2,
    }
    pipeline = PipelineItem(
        slot_start=slot, camera_key="cam01", state=PipelineState.VERIFIED_UPLOADED,
        root=str(root), payload={"mode": "production"},
    )
    row = {
        "capture_status": "captured", "upload_status": "uploaded",
        "manifest_r2_key": "recordings/safe/manifest.json",
        "uploaded_at": "2026-08-31T09:00:00+00:00",
    }
    inspector = MountInspector(mount)
    guard = capture_prune_root_guard(root, expected_root=root, inspector=inspector)
    return root, bundle, Heads(heads), Repository(row), Store(pipeline), inspector, guard


def test_prune_plan_requires_exact_mount_root_and_rejects_symlinks(tmp_path: Path) -> None:
    root, bundle, heads, repo, store, inspector, _guard = make_bundle(tmp_path)
    with pytest.raises(PruneSafetyError):
        capture_prune_root_guard(root, expected_root=root / "wrong", inspector=inspector)
    link = root / "linked"
    link.symlink_to(bundle, target_is_directory=True)
    with pytest.raises(PruneSafetyError):
        capture_prune_root_guard(link, expected_root=link, inspector=inspector)


def test_prune_plan_is_deterministic_and_requires_all_provenance(tmp_path: Path) -> None:
    root, _bundle, heads, repo, store, inspector, guard = make_bundle(tmp_path)
    now = datetime(2026, 9, 2, 12, 0, tzinfo=KST)

    first = build_prune_plan(root, uploader=heads, repository=repo, store=store, now=now, guard=guard)
    second = build_prune_plan(root, uploader=heads, repository=repo, store=store, now=now, guard=guard)

    assert len(first.candidates) == 1
    assert first.plan_digest == second.plan_digest
    assert first.to_public_dict()["candidate_count"] == 1
    assert str(root) not in json.dumps(first.to_public_dict())

    heads.values["recordings/safe/video.mp4"]["sha256"] = "0" * 64
    rejected = build_prune_plan(root, uploader=heads, repository=repo, store=store, now=now, guard=guard)
    assert rejected.candidates == ()
    assert rejected.excluded["r2_mismatch"] == 1


@pytest.mark.parametrize("reason", ["partial", "current_night", "pipeline", "database", "active"])
def test_prune_plan_excludes_unfinalized_or_active_bundles(tmp_path: Path, reason: str) -> None:
    night = "2026-09-01" if reason == "current_night" else "2026-08-30"
    root, _bundle, heads, repo, store, inspector, guard = make_bundle(
        tmp_path, partial=reason == "partial", night=night
    )
    if reason == "pipeline":
        store.item = PipelineItem(store.item.slot_start, "cam01", PipelineState.RAW_UPLOADED, str(root), {})
    elif reason == "database":
        assert repo.row is not None
        repo.row["upload_status"] = "pending"
    elif reason == "active":
        store.claim = "running"

    plan = build_prune_plan(
        root, uploader=heads, repository=repo, store=store,
        now=datetime(2026, 9, 2, 12, 0, tzinfo=KST), guard=guard,
    )

    assert plan.candidates == ()
    assert sum(plan.excluded.values()) == 1


def test_execute_requires_same_digest_and_revalidated_plan_then_writes_receipts(tmp_path: Path) -> None:
    root, bundle, heads, repo, store, inspector, guard = make_bundle(tmp_path)
    now = datetime(2026, 9, 2, 12, 0, tzinfo=KST)
    plan = build_prune_plan(root, uploader=heads, repository=repo, store=store, now=now, guard=guard)
    receipt_dir = tmp_path / "manager-audit"

    with pytest.raises(PruneSafetyError):
        execute_prune(plan, supplied_digest="0" * 64, receipt_dir=receipt_dir, rebuild_plan=lambda: plan)
    assert bundle.is_dir()

    receipt = execute_prune(
        plan, supplied_digest=plan.plan_digest, receipt_dir=receipt_dir,
        rebuild_plan=lambda: build_prune_plan(
            root, uploader=heads, repository=repo, store=store, now=now,
            guard=capture_prune_root_guard(root, expected_root=root, inspector=inspector),
        ),
    )

    assert receipt.deleted_count == 1
    assert not bundle.exists()
    assert (receipt_dir.stat().st_mode & 0o777) == 0o700
    receipts = sorted(receipt_dir.iterdir())
    assert len(receipts) == 2
    assert all((path.stat().st_mode & 0o777) == 0o600 for path in receipts)


def test_execute_stops_before_delete_when_evidence_drifted(tmp_path: Path) -> None:
    root, bundle, heads, repo, store, _inspector, guard = make_bundle(tmp_path)
    now = datetime(2026, 9, 2, 12, 0, tzinfo=KST)
    plan = build_prune_plan(root, uploader=heads, repository=repo, store=store, now=now, guard=guard)
    heads.values["recordings/safe/video.mp4"]["ContentLength"] = 999

    with pytest.raises(PruneSafetyError):
        execute_prune(
            plan, supplied_digest=plan.plan_digest,
            receipt_dir=tmp_path / "audit",
            rebuild_plan=lambda: build_prune_plan(
                root, uploader=heads, repository=repo, store=store, now=now, guard=guard
            ),
        )

    assert bundle.is_dir()
    assert (bundle / "video.mp4").is_file()


def test_execute_rejects_bundle_inode_swap_after_revalidation(tmp_path: Path) -> None:
    root, bundle, heads, repo, store, _inspector, guard = make_bundle(tmp_path)
    now = datetime(2026, 9, 2, 12, 0, tzinfo=KST)
    plan = build_prune_plan(root, uploader=heads, repository=repo, store=store, now=now, guard=guard)
    original = bundle.with_name("original-preserved")
    bundle.rename(original)
    bundle.mkdir()
    for source in original.iterdir():
        (bundle / source.name).write_bytes(source.read_bytes())

    with pytest.raises(PruneSafetyError, match="identity"):
        execute_prune(
            plan, supplied_digest=plan.plan_digest, receipt_dir=tmp_path / "audit",
            rebuild_plan=lambda: plan,
        )

    assert bundle.is_dir()
    assert original.is_dir()


def test_prune_receipts_are_fsynced_before_and_after_delete(tmp_path: Path, monkeypatch) -> None:
    root, _bundle, heads, repo, store, _inspector, guard = make_bundle(tmp_path)
    now = datetime(2026, 9, 2, 12, 0, tzinfo=KST)
    plan = build_prune_plan(root, uploader=heads, repository=repo, store=store, now=now, guard=guard)
    calls: list[int] = []
    monkeypatch.setattr("backend.rap_c500g_local_prune.os.fsync", calls.append)

    execute_prune(
        plan, supplied_digest=plan.plan_digest, receipt_dir=tmp_path / "audit",
        rebuild_plan=lambda: plan,
    )

    assert len(calls) >= 4
