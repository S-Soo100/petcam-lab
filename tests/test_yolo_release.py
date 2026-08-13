from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from backend.yolo_release import (
    FixedTestMetrics,
    ReleaseError,
    YoloReleaseManifest,
    create_immutable_release,
    load_release_manifest,
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
        ),
        fixed_test=FixedTestMetrics(
            tp=53,
            fp=19,
            fn=37,
            precision=0.7361111111111112,
            recall=0.5888888888888889,
        ),
    )


def test_create_release_copies_exact_checkpoint_and_writes_read_only_manifest(
    tmp_path: Path,
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


def test_create_release_rejects_symlink_source(tmp_path: Path) -> None:
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
