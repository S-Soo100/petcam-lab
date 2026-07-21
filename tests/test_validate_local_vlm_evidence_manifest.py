"""local-vlm-evidence-analyst manifest 계약 validator 단위 테스트.

이 validator 는 design/TEST-SHEET §5 의 표본 계약(180 unique · 6 strata×30 ·
dev120/holdout60 · episode dedup · camera≥2/date≥3 · GT 완전성 · 반복 30(strata×5,
정확히 2 extra key)) 을 기계 검증한다. Supabase 를 절대 조회하지 않는 순수 함수 계약.
"""

from __future__ import annotations

import copy

import pytest

from scripts.validate_local_vlm_evidence_manifest import (
    STRATA,
    build_measured_keys,
    compute_gt_sha256,
    compute_manifest_sha256,
    validate_manifest,
)

# 각 stratum: dev 20 / holdout 10 = 30. 6 strata = 180.
_CAMERAS = ["cam-a", "cam-b", "cam-c"]
_DATES = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"]


def _gt_row(durable_key: str) -> dict:
    return {
        "durable_key": durable_key,
        "presence_observation": "present",
        "visibility": "clear",
        "motion_extent": "body_translation",
        "body_region_candidates": ["whole"],
        "object_candidates": ["unknown"],
        "human_uncertain": False,
        "reason": "gecko visibly crossing",
    }


def _build_valid() -> tuple[dict, list[dict]]:
    clips: list[dict] = []
    n = 0
    for s_idx, stratum in enumerate(STRATA):
        for i in range(30):
            split = "dev" if i < 20 else "holdout"
            # camera 를 stratum 안에서 3분할 → 한 카메라 비중 ≤ 60%
            cam = _CAMERAS[(i) % 3]
            date = _DATES[(s_idx + i) % 4]
            dk = f"clip-{stratum}-{i:02d}"
            clips.append(
                {
                    "durable_key": dk,
                    "clip_id": f"uuid-{n:04d}",
                    "strata": stratum,
                    "split": split,
                    "camera_id": cam,
                    "capture_date": date,
                    "episode_id": f"ep-{stratum}-{i:02d}",
                    "source": "camera",
                    "r2_key": f"clips/{dk}.mp4",
                }
            )
            n += 1

    # 반복: holdout(i>=20) 에서 stratum 별 5개 = 30
    repeat_clips: list[str] = []
    for stratum in STRATA:
        for i in range(20, 25):
            repeat_clips.append(f"clip-{stratum}-{i:02d}")

    gt_rows = [_gt_row(c["durable_key"]) for c in clips]

    manifest = {
        "experiment": "local-vlm-evidence-analyst",
        "schema_version": "manifest-v1",
        "strata": list(STRATA),
        "clips": clips,
        "repeat_clips": repeat_clips,
    }
    manifest["manifest_sha256"] = compute_manifest_sha256(manifest)
    manifest["gt_sha256"] = compute_gt_sha256(gt_rows)
    return manifest, gt_rows


# --- 정상 케이스 -------------------------------------------------------------


def test_valid_manifest_has_no_errors() -> None:
    manifest, gt_rows = _build_valid()
    assert validate_manifest(manifest, gt_rows) == []


def test_valid_counts() -> None:
    manifest, _ = _build_valid()
    assert len(manifest["clips"]) == 180
    dev = [c for c in manifest["clips"] if c["split"] == "dev"]
    holdout = [c for c in manifest["clips"] if c["split"] == "holdout"]
    assert len(dev) == 120
    assert len(holdout) == 60
    assert len(manifest["repeat_clips"]) == 30


# --- 무결성 위반 -------------------------------------------------------------


def test_duplicate_clip_detected() -> None:
    manifest, gt_rows = _build_valid()
    manifest["clips"].append(copy.deepcopy(manifest["clips"][0]))
    errors = validate_manifest(manifest, gt_rows)
    assert any(e.startswith("DUPLICATE_CLIP") for e in errors)
    assert any(e.startswith("CLIP_COUNT") for e in errors)


def test_episode_leakage_dev_holdout() -> None:
    manifest, gt_rows = _build_valid()
    # holdout clip 의 episode 를 dev clip 과 동일하게 → 교차 episode
    dev_ep = next(c for c in manifest["clips"] if c["split"] == "dev")["episode_id"]
    hold = next(c for c in manifest["clips"] if c["split"] == "holdout")
    hold["episode_id"] = dev_ep
    errors = validate_manifest(manifest, gt_rows)
    assert any(e.startswith("EPISODE_DUPLICATE") for e in errors)
    assert any(e.startswith("DEV_HOLDOUT_EPISODE_LEAKAGE") for e in errors)


def test_dev_holdout_clip_leakage() -> None:
    manifest, gt_rows = _build_valid()
    # dev clip 의 durable_key 를 holdout clip 이 재사용 → clip leakage + 중복
    dev = next(c for c in manifest["clips"] if c["split"] == "dev")
    hold = next(c for c in manifest["clips"] if c["split"] == "holdout")
    hold["durable_key"] = dev["durable_key"]
    errors = validate_manifest(manifest, gt_rows)
    assert any(e.startswith("DUPLICATE_CLIP") for e in errors)
    assert any(e.startswith("DEV_HOLDOUT_CLIP_LEAKAGE") for e in errors)


def test_camera_diversity_lt_2() -> None:
    manifest, gt_rows = _build_valid()
    for c in manifest["clips"]:
        c["camera_id"] = "cam-a"
    errors = validate_manifest(manifest, gt_rows)
    assert "CAMERA_DIVERSITY" in errors


def test_date_diversity_lt_3() -> None:
    manifest, gt_rows = _build_valid()
    for c in manifest["clips"]:
        c["capture_date"] = "2026-07-01"
    errors = validate_manifest(manifest, gt_rows)
    assert "DATE_DIVERSITY" in errors


def test_missing_evidence_gt() -> None:
    manifest, gt_rows = _build_valid()
    dropped = gt_rows[:-1]  # 마지막 clip GT 누락
    manifest["gt_sha256"] = compute_gt_sha256(dropped)
    errors = validate_manifest(manifest, dropped)
    assert any(e.startswith("MISSING_GT") for e in errors)


def test_incomplete_gt_field() -> None:
    manifest, gt_rows = _build_valid()
    gt_rows[0]["motion_extent"] = None  # 필수 축 null
    manifest["gt_sha256"] = compute_gt_sha256(gt_rows)
    errors = validate_manifest(manifest, gt_rows)
    assert any(e.startswith("MISSING_GT") for e in errors)


def test_stratum_count_wrong() -> None:
    manifest, gt_rows = _build_valid()
    # 한 stratum 에서 clip 하나 제거 → 29, 다른 곳에 추가하면 불균형
    victim = next(c for c in manifest["clips"] if c["strata"] == STRATA[0])
    manifest["clips"].remove(victim)
    gt_rows = [r for r in gt_rows if r["durable_key"] != victim["durable_key"]]
    manifest["gt_sha256"] = compute_gt_sha256(gt_rows)
    errors = validate_manifest(manifest, gt_rows)
    assert any(e.startswith("STRATUM_COUNT") for e in errors)


# --- 반복 계약 ---------------------------------------------------------------


def test_repeat_not_30() -> None:
    manifest, gt_rows = _build_valid()
    manifest["repeat_clips"] = manifest["repeat_clips"][:-1]
    errors = validate_manifest(manifest, gt_rows)
    assert any(e.startswith("REPEAT_COUNT") for e in errors)


def test_repeat_must_be_holdout() -> None:
    manifest, gt_rows = _build_valid()
    # dev clip durable_key 를 반복셋에 밀어넣음
    dev_dk = next(c["durable_key"] for c in manifest["clips"] if c["split"] == "dev")
    manifest["repeat_clips"][0] = dev_dk
    errors = validate_manifest(manifest, gt_rows)
    assert any(e.startswith("REPEAT_NOT_HOLDOUT") for e in errors)


def test_repeat_strata_not_5() -> None:
    manifest, gt_rows = _build_valid()
    # 첫 stratum 반복 clip 하나를 다른 stratum holdout clip 으로 교체
    other = next(
        c["durable_key"]
        for c in manifest["clips"]
        if c["split"] == "holdout" and c["strata"] == STRATA[1]
        and c["durable_key"] not in manifest["repeat_clips"]
    )
    manifest["repeat_clips"][0] = other
    errors = validate_manifest(manifest, gt_rows)
    assert any(e.startswith("REPEAT_STRATUM_COUNT") for e in errors)


# --- hash ------------------------------------------------------------------


def test_manifest_hash_mismatch() -> None:
    manifest, gt_rows = _build_valid()
    manifest["manifest_sha256"] = "0" * 64
    errors = validate_manifest(manifest, gt_rows)
    assert "MANIFEST_HASH_MISMATCH" in errors


def test_gt_hash_mismatch() -> None:
    manifest, gt_rows = _build_valid()
    manifest["gt_sha256"] = "0" * 64
    errors = validate_manifest(manifest, gt_rows)
    assert "GT_HASH_MISMATCH" in errors


# --- measured keys ----------------------------------------------------------


def test_build_measured_keys_240_total() -> None:
    manifest, _ = _build_valid()
    keys = build_measured_keys(manifest)
    assert len(keys) == 240


def test_build_measured_keys_repeat_counts() -> None:
    manifest, _ = _build_valid()
    keys = build_measured_keys(manifest)
    from collections import Counter

    per_clip = Counter(k["durable_key"] for k in keys)
    repeat_set = set(manifest["repeat_clips"])
    for dk, count in per_clip.items():
        if dk in repeat_set:
            assert count == 3, f"{dk} repeat clip should run 3x, got {count}"
        else:
            assert count == 1, f"{dk} non-repeat should run 1x, got {count}"
    # measured_key 유일성
    assert len({k["measured_key"] for k in keys}) == 240


def test_build_measured_keys_deterministic() -> None:
    manifest, _ = _build_valid()
    a = build_measured_keys(manifest, repeat_seed=20260721)
    b = build_measured_keys(manifest, repeat_seed=20260721)
    assert [k["measured_key"] for k in a] == [k["measured_key"] for k in b]


def test_build_measured_keys_no_adjacent_same_clip() -> None:
    manifest, _ = _build_valid()
    keys = build_measured_keys(manifest)
    for prev, cur in zip(keys, keys[1:]):
        assert prev["durable_key"] != cur["durable_key"], (
            "같은 clip 의 반복 실행이 연속으로 배치되면 안 됨"
        )
