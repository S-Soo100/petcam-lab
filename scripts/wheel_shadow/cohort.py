"""frozen cohort 조립 + canonical SHA-256 (동시 라벨링 안전 계약의 재현 앵커).

SHA 는 canonical JSON(sort_keys, 구분자 최소) 으로 계산 → 입력 순서 무관 결정론.
clip_ids 는 항상 정렬해 라벨링 순서·삽입 순서에 흔들리지 않게 한다.
"""
from __future__ import annotations

import hashlib
import json


def cohort_sha256(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_frozen_cohort(
    camera_name: str,
    camera_id: str,
    started_at_range: list[str],
    clips: list[dict],
    known_wheel_gt_clip_ids: list[str],
    gt_snapshot_watermark: str | None,
) -> dict:
    clip_map = {c["clip_id"]: c for c in clips}
    clip_ids = sorted(clip_map)
    identity = {cid: clip_map[cid] for cid in clip_ids}
    core = {
        "camera_name": camera_name,
        "camera_id": camera_id,
        "started_at_range": started_at_range,
        "clip_ids": clip_ids,
        "python_evidence_run_identity": identity,
        "known_wheel_gt_clip_ids": sorted(known_wheel_gt_clip_ids),
        "gt_snapshot_watermark": gt_snapshot_watermark,
    }
    return {**core, "cohort_sha256": cohort_sha256(core)}
