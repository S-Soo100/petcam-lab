from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path

import pytest

import backend.yolo_release as yolo_release
from backend.yolo_release import (
    V25_CHECKPOINT_SHA256,
    FixedTestMetrics,
    ReleaseError,
    YoloReleaseManifest,
    create_immutable_release,
    load_release_manifest,
    v25_release_manifest,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _manifest(payload: bytes = b"checkpoint") -> YoloReleaseManifest:
    return YoloReleaseManifest(
        schema="petcam-yolo-release-v1",
        model_version="yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018",
        checkpoint_sha256=_sha256(payload),
        checkpoint_size=len(payload),
        candidate="warm-start",
        threshold=0.25,
        image_size=960,
        iou=0.7,
        max_detections=20,
        evaluation_tier="development",
        future_holdout_required=True,
        allowed_use="labeling_bbox_assist_only",
        forbidden_uses=(
            "gt_auto_confirm",
            "absence_decision",
            "gme_routing",
            "r2_classification",
            "deletion",
            "vlm_skip",
            "behavior_name",
            "event_grouping",
        ),
        fixed_test=FixedTestMetrics(
            tp=53,
            fp=19,
            fn=37,
            precision=0.7361111111111112,
            recall=0.5888888888888889,
        ),
    )


@pytest.fixture
def allow_synthetic_v23_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    original = yolo_release.release_manifest_for_version

    def resolve(model_version: str) -> YoloReleaseManifest:
        if model_version == _manifest().model_version:
            return _manifest()
        return original(model_version)

    monkeypatch.setattr(yolo_release, "release_manifest_for_version", resolve)


def test_v25_manifest_is_exact_development_owner_preview_contract() -> None:
    manifest = v25_release_manifest()

    assert manifest.model_version == (
        "yolo26n-owner-dataset-v2.5-warm-start+2b128f105e89"
    )
    assert manifest.checkpoint_sha256 == V25_CHECKPOINT_SHA256
    assert manifest.checkpoint_size == 5_400_517
    assert manifest.threshold == 0.20
    assert manifest.allowed_use == "owner_preview_bbox_suggestion_only"
    assert manifest.fixed_test == FixedTestMetrics(
        tp=68,
        fp=25,
        fn=22,
        precision=0.7311827956989247,
        recall=0.7555555555555555,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("threshold", 0.25),
        ("checkpoint_size", 5_400_518),
        ("checkpoint_sha256", "0" * 64),
        ("allowed_use", "labeling_bbox_assist_only"),
        (
            "fixed_test",
            FixedTestMetrics(
                tp=67,
                fp=25,
                fn=22,
                precision=0.7311827956989247,
                recall=0.7555555555555555,
            ),
        ),
    ],
)
def test_create_release_rejects_mutated_v25_contract(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    from dataclasses import replace

    manifest = replace(v25_release_manifest(), **{field: value})

    with pytest.raises(ReleaseError, match="release_manifest_invalid"):
        create_immutable_release(
            source=tmp_path / "missing.pt",
            release_root=tmp_path / "releases",
            manifest=manifest,
        )


def test_create_release_copies_exact_checkpoint_and_writes_read_only_manifest(
    tmp_path: Path,
    allow_synthetic_v23_manifest: None,
) -> None:
    source = tmp_path / "source.pt"
    source.write_bytes(b"checkpoint")

    checkpoint, manifest_path = create_immutable_release(
        source=source,
        release_root=tmp_path / "releases",
        manifest=_manifest(),
    )

    assert checkpoint.read_bytes() == b"checkpoint"
    assert stat.S_IMODE(checkpoint.stat().st_mode) == 0o444
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o444
    assert load_release_manifest(manifest_path) == _manifest()
    assert list(checkpoint.parent.parent.glob(".petcam-yolo-release-*")) == []


@pytest.mark.parametrize(
    ("payload", "manifest"),
    [
        (b"wrong-size", _manifest()),
        (b"checkpoinu", _manifest()),
    ],
)
def test_create_release_rejects_source_identity_mismatch_without_residue(
    tmp_path: Path,
    payload: bytes,
    manifest: YoloReleaseManifest,
    allow_synthetic_v23_manifest: None,
) -> None:
    source = tmp_path / "source.pt"
    source.write_bytes(payload)
    release_root = tmp_path / "releases"

    with pytest.raises(ReleaseError, match="source_identity_invalid"):
        create_immutable_release(
            source=source,
            release_root=release_root,
            manifest=manifest,
        )

    assert not release_root.exists() or list(release_root.iterdir()) == []


def test_create_release_rejects_symlink_source(
    tmp_path: Path,
    allow_synthetic_v23_manifest: None,
) -> None:
    real_source = tmp_path / "real.pt"
    real_source.write_bytes(b"checkpoint")
    source = tmp_path / "source.pt"
    source.symlink_to(real_source)

    with pytest.raises(ReleaseError, match="source_identity_invalid"):
        create_immutable_release(
            source=source,
            release_root=tmp_path / "releases",
            manifest=_manifest(),
        )


def test_existing_exact_release_is_idempotent_but_conflict_fails_closed(
    tmp_path: Path,
    allow_synthetic_v23_manifest: None,
) -> None:
    source = tmp_path / "source.pt"
    source.write_bytes(b"checkpoint")
    release_root = tmp_path / "releases"

    first = create_immutable_release(
        source=source,
        release_root=release_root,
        manifest=_manifest(),
    )
    second = create_immutable_release(
        source=source,
        release_root=release_root,
        manifest=_manifest(),
    )
    assert second == first

    first[0].chmod(0o644)
    first[0].write_bytes(b"tampered!")
    with pytest.raises(ReleaseError, match="release_identity_invalid"):
        create_immutable_release(
            source=source,
            release_root=release_root,
            manifest=_manifest(),
        )


def test_load_manifest_rejects_unsafe_usage_or_threshold(tmp_path: Path) -> None:
    manifest = _manifest()
    payload = manifest.to_dict()
    payload["allowed_use"] = "absence_decision"
    payload["threshold"] = 0.5
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(ReleaseError, match="release_manifest_invalid"):
        load_release_manifest(path)


def test_release_cli_fails_closed_without_printing_source_path(tmp_path: Path) -> None:
    source = tmp_path / "private-training-path" / "best.pt"
    source.parent.mkdir()
    source.write_bytes(b"wrong")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/create_yolo_v23_release.py",
            "--source",
            str(source),
            "--release-root",
            str(tmp_path / "releases"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout) == {
        "status": "failed",
        "error": "source_identity_invalid",
    }
    assert str(source) not in completed.stdout


def test_concurrent_release_creation_is_idempotent_without_temp_residue(
    tmp_path: Path,
    allow_synthetic_v23_manifest: None,
) -> None:
    source = tmp_path / "source.pt"
    source.write_bytes(b"checkpoint")
    release_root = tmp_path / "releases"
    barrier = Barrier(8)

    def create() -> tuple[Path, Path]:
        barrier.wait()
        return create_immutable_release(
            source=source,
            release_root=release_root,
            manifest=_manifest(),
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: create(), range(8)))

    assert results == [results[0]] * 8
    assert list(release_root.glob(".petcam-yolo-release-*")) == []
    assert load_release_manifest(results[0][1]) == _manifest()
