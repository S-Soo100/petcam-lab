"""local-vlm-evidence-analyst 표본 manifest·GT 계약 validator.

설계 SOT: `docs/superpowers/specs/2026-07-21-mac-mini-local-vlm-evidence-analyst-design.md` §6
       · `experiments/local-vlm-evidence-analyst/TEST-SHEET.md` §5.

순수 함수 계약이다. **Supabase 를 조회하지 않는다.** manifest(dict) 와 GT rows(list[dict]) 를
받아 사전 등록 계약 위반을 안정적인 error code 리스트로 돌려준다. CLI 는 위반이 하나라도 있으면
nonzero 로 종료한다.

왜 순수 함수인가: 사전 등록(pre-registration) 단계에서 표본이 계약을 만족하는지 감사 가능해야
하고, 재현 가능한 채점을 위해 build_measured_keys 가 seed 로만 결정되어야 하기 때문. (TS/JS 로
치면 zod 스키마 검증 + 순수 셔플 함수와 같은 역할.)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

# design §6.1 / TEST-SHEET §5.1 의 6 strata 고정 순서
STRATA: tuple[str, ...] = (
    "absent",
    "big_move",
    "rest_micro",
    "lick_water_food",
    "wheel_object",
    "hardcase",
)

_SPLITS = ("dev", "holdout")

# design §6 계약: 총 180, stratum 별 30(dev 20/holdout 10), 반복 30(stratum 별 5)
TOTAL_CLIPS = 180
PER_STRATUM = 30
DEV_PER_STRATUM = 20
HOLDOUT_PER_STRATUM = 10
DEV_TOTAL = 120
HOLDOUT_TOTAL = 60
REPEAT_TOTAL = 30
REPEAT_PER_STRATUM = 5
REPEAT_RUNS = 3  # 기본 1 + 추가 2
MEASURED_KEYS_TOTAL = 240

# GT worksheet 필수 축 (TEST-SHEET §6). observation 자유문장은 정량 대상 아님.
_REQUIRED_GT_FIELDS = (
    "presence_observation",
    "visibility",
    "motion_extent",
    "body_region_candidates",
    "object_candidates",
    "human_uncertain",
)

_DEFAULT_REPEAT_SEED = 20260721


# --- canonical hashing ------------------------------------------------------


def _canonical_bytes(obj: object) -> bytes:
    """정렬·공백 제거된 canonical JSON. 같은 논리 구조 → 같은 SHA-256."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def compute_manifest_sha256(manifest: dict) -> str:
    """manifest 의 실질 내용(clips·strata·repeat) SHA-256. self-hash 필드는 제외한다."""
    payload = {
        "experiment": manifest.get("experiment"),
        "strata": manifest.get("strata"),
        "clips": manifest.get("clips"),
        "repeat_clips": manifest.get("repeat_clips"),
    }
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def compute_gt_sha256(gt_rows: list[dict]) -> str:
    return hashlib.sha256(_canonical_bytes(gt_rows)).hexdigest()


# --- validation -------------------------------------------------------------


def validate_manifest(manifest: dict, gt_rows: list[dict]) -> list[str]:
    """계약 위반 error code 리스트 반환. 빈 리스트면 통과.

    code 는 접두어 기반이라 테스트/CLI 가 `startswith` 로 안정적으로 매칭한다.
    """
    errors: list[str] = []
    clips = manifest.get("clips") or []
    repeat_clips = manifest.get("repeat_clips") or []

    # --- 총 개수 ---
    if len(clips) != TOTAL_CLIPS:
        errors.append(f"CLIP_COUNT:{len(clips)}!={TOTAL_CLIPS}")

    # --- 중복 clip (durable_key / clip_id) ---
    dk_counts = Counter(c.get("durable_key") for c in clips)
    for dk, n in dk_counts.items():
        if n > 1:
            errors.append(f"DUPLICATE_CLIP:{dk}")
    id_counts = Counter(c.get("clip_id") for c in clips)
    for cid, n in id_counts.items():
        if n > 1:
            errors.append(f"DUPLICATE_CLIP_ID:{cid}")

    # --- split 유효성 + 개수 ---
    for c in clips:
        if c.get("split") not in _SPLITS:
            errors.append(f"INVALID_SPLIT:{c.get('durable_key')}:{c.get('split')}")
    dev = [c for c in clips if c.get("split") == "dev"]
    holdout = [c for c in clips if c.get("split") == "holdout"]
    if len(dev) != DEV_TOTAL:
        errors.append(f"SPLIT_DEV_COUNT:{len(dev)}!={DEV_TOTAL}")
    if len(holdout) != HOLDOUT_TOTAL:
        errors.append(f"SPLIT_HOLDOUT_COUNT:{len(holdout)}!={HOLDOUT_TOTAL}")

    # --- stratum 개수 + split 균형 ---
    declared = list(manifest.get("strata") or STRATA)
    for c in clips:
        if c.get("strata") not in declared:
            errors.append(f"UNKNOWN_STRATUM:{c.get('durable_key')}:{c.get('strata')}")
    for stratum in declared:
        s_clips = [c for c in clips if c.get("strata") == stratum]
        if len(s_clips) != PER_STRATUM:
            errors.append(f"STRATUM_COUNT:{stratum}:{len(s_clips)}!={PER_STRATUM}")
        s_dev = sum(1 for c in s_clips if c.get("split") == "dev")
        s_hold = sum(1 for c in s_clips if c.get("split") == "holdout")
        if s_dev != DEV_PER_STRATUM:
            errors.append(f"STRATUM_DEV_COUNT:{stratum}:{s_dev}!={DEV_PER_STRATUM}")
        if s_hold != HOLDOUT_PER_STRATUM:
            errors.append(
                f"STRATUM_HOLDOUT_COUNT:{stratum}:{s_hold}!={HOLDOUT_PER_STRATUM}"
            )

    # --- episode 중복 + dev/holdout episode 누출 ---
    ep_to_splits: dict[str, set[str]] = {}
    ep_counts: Counter = Counter()
    for c in clips:
        ep = c.get("episode_id")
        ep_counts[ep] += 1
        ep_to_splits.setdefault(ep, set()).add(c.get("split"))
    for ep, n in ep_counts.items():
        if n > 1:
            errors.append(f"EPISODE_DUPLICATE:{ep}")
    for ep, splits in ep_to_splits.items():
        if "dev" in splits and "holdout" in splits:
            errors.append(f"DEV_HOLDOUT_EPISODE_LEAKAGE:{ep}")

    # --- dev↔holdout durable_key 누출 (같은 clip 이 양쪽에) ---
    dk_to_splits: dict[str, set[str]] = {}
    for c in clips:
        dk_to_splits.setdefault(c.get("durable_key"), set()).add(c.get("split"))
    for dk, splits in dk_to_splits.items():
        if "dev" in splits and "holdout" in splits:
            errors.append(f"DEV_HOLDOUT_CLIP_LEAKAGE:{dk}")

    # --- camera / date diversity ---
    cameras = {c.get("camera_id") for c in clips}
    dates = {c.get("capture_date") for c in clips}
    if len(cameras) < 2:
        errors.append("CAMERA_DIVERSITY")
    if len(dates) < 3:
        errors.append("DATE_DIVERSITY")

    # --- GT 완전성 ---
    gt_by_key: dict[str, dict] = {}
    for row in gt_rows:
        gt_by_key[row.get("durable_key")] = row
    for c in clips:
        dk = c.get("durable_key")
        row = gt_by_key.get(dk)
        if row is None or not _gt_row_complete(row):
            errors.append(f"MISSING_GT:{dk}")

    # --- 반복 계약 ---
    if len(repeat_clips) != REPEAT_TOTAL:
        errors.append(f"REPEAT_COUNT:{len(repeat_clips)}!={REPEAT_TOTAL}")
    rep_counts = Counter(repeat_clips)
    for dk, n in rep_counts.items():
        if n > 1:
            errors.append(f"REPEAT_DUPLICATE:{dk}")
    holdout_keys = {c.get("durable_key") for c in holdout}
    stratum_by_key = {c.get("durable_key"): c.get("strata") for c in clips}
    for dk in repeat_clips:
        if dk not in holdout_keys:
            errors.append(f"REPEAT_NOT_HOLDOUT:{dk}")
    rep_stratum_counts = Counter(
        stratum_by_key.get(dk) for dk in repeat_clips if dk in stratum_by_key
    )
    for stratum in declared:
        got = rep_stratum_counts.get(stratum, 0)
        if got != REPEAT_PER_STRATUM:
            errors.append(f"REPEAT_STRATUM_COUNT:{stratum}:{got}!={REPEAT_PER_STRATUM}")

    # --- hash ---
    expected_manifest = manifest.get("manifest_sha256")
    if expected_manifest is not None:
        if expected_manifest != compute_manifest_sha256(manifest):
            errors.append("MANIFEST_HASH_MISMATCH")
    expected_gt = manifest.get("gt_sha256")
    if expected_gt is not None:
        if expected_gt != compute_gt_sha256(gt_rows):
            errors.append("GT_HASH_MISMATCH")

    return errors


def _gt_row_complete(row: dict) -> bool:
    for field in _REQUIRED_GT_FIELDS:
        if field not in row:
            return False
        val = row[field]
        if val is None:
            return False
        if field in ("body_region_candidates", "object_candidates"):
            if not isinstance(val, list) or len(val) == 0:
                return False
    return True


# --- measured keys ----------------------------------------------------------


def build_measured_keys(
    manifest: dict, repeat_seed: int = _DEFAULT_REPEAT_SEED
) -> list[dict]:
    """240 measured key 를 결정론적으로 생성한다.

    - 180 clip 각 1회(run 0)
    - 반복 30 clip 은 run 1·run 2 추가 → 각 3회
    - seed 로 셔플하되 같은 clip 의 실행이 연속되지 않게 재배치한다.
    """
    clips = manifest.get("clips") or []
    repeat_set = set(manifest.get("repeat_clips") or [])

    keys: list[dict] = []
    for c in clips:
        dk = c.get("durable_key")
        runs = REPEAT_RUNS if dk in repeat_set else 1
        for run in range(runs):
            keys.append(
                {
                    "measured_key": f"{dk}#run{run}",
                    "durable_key": dk,
                    "clip_id": c.get("clip_id"),
                    "strata": c.get("strata"),
                    "split": c.get("split"),
                    "run_index": run,
                }
            )

    rng = random.Random(repeat_seed)
    rng.shuffle(keys)
    return _spread_adjacent(keys)


def _spread_adjacent(keys: list[dict]) -> list[dict]:
    """인접한 같은 durable_key 를 뒤쪽 비충돌 원소와 swap 해 분산한다 (결정론적)."""
    n = len(keys)
    for i in range(1, n):
        if keys[i]["durable_key"] != keys[i - 1]["durable_key"]:
            continue
        # 뒤에서 i-1 과도 i+1 과도 겹치지 않는 첫 원소를 찾아 swap
        for j in range(i + 1, n):
            cand = keys[j]["durable_key"]
            prev = keys[i - 1]["durable_key"]
            nxt = keys[i + 1]["durable_key"] if i + 1 < n else None
            j_prev = keys[j - 1]["durable_key"]
            j_next = keys[j + 1]["durable_key"] if j + 1 < n else None
            # swap 후 i 위치·j 위치 모두 인접 충돌이 없어야 함
            if cand != prev and cand != nxt and keys[i]["durable_key"] != j_prev and keys[i]["durable_key"] != j_next:
                keys[i], keys[j] = keys[j], keys[i]
                break
    return keys


# --- CLI --------------------------------------------------------------------


def _load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--gt", required=True, type=Path)
    args = parser.parse_args(argv)

    manifest = _load_json(args.manifest)
    gt = _load_json(args.gt)
    gt_rows = gt if isinstance(gt, list) else gt.get("rows", [])

    errors = validate_manifest(manifest, gt_rows)
    if errors:
        print(f"MANIFEST_INVALID errors={len(errors)}")
        for e in errors:
            print(f"  {e}")
        return 1
    print(
        f"MANIFEST_OK clips={len(manifest.get('clips', []))} "
        f"repeat={len(manifest.get('repeat_clips', []))} "
        f"measured_keys={len(build_measured_keys(manifest))}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
