"""VLM 워커 회귀 가드 — 203건 통합 평가셋 인퍼런스 + 정확도/비용 측정.

⚠️ 퇴역 2026-06-12 — Gemini API 포기 피벗(specs/experiment-claude-montage-v2.md §0).
Gemini 인퍼런스(main) 신규 실행 금지. 단 load_eval_set/merge_label/가격상수는 Claude 트랙
스크립트가 계속 import 하므로 파일은 유지.

## 목적
production 워커 (`backend/vlm/`) 의 정확도/비용 측정. 잔존 비용 추적도 같은 실행에서 산출.

## 평가셋 운영 (2026-06-08 변경 — 159 동결 → 203 통합)
사용자 결정: 159 기존 + 44 eval-0608 = **203 단일 평가셋으로 운영**. 과거 159 동결
(v3.5 floor 85.5% 비교 가드)은 해제. v3.5 floor 직접비교가 필요하면 `load_eval_set_0608`
(44 신규)을 빼서 159 부분집합으로 복원 가능 — 완전히 잃지 않음. 단 203 직접 정확도는
hand_feeding(OOD) 19건이 섞여 v3.5(클래스 없음)엔 불리하므로, v3.5↔v3.6 비교 시
`eval_vlm_v36_handfeeding` 처럼 P0/OOD 분리 분석 권장.
(메모리 `project_vlm_v35_baseline_lock` 갱신됨)

## 동치 보장
- 워커 코드 그대로 재사용: `backend.vlm.gemini_client.classify_clip` + `download_clip_bytes` +
  `backend.vlm.prompts.build_system_prompt`. SOT (`web/src/lib/prompts.ts`) 와 mirror.
- 평가셋: human GT + has_motion + r2_key 클립 전부 = 203건 (159 + 44 eval-0608).
- DB INSERT 안 함 — production `behavior_logs` 무손상. JSONL 결과는 `/tmp/vlm-regression.jsonl`.

## 실행
    uv run python -m scripts.eval_vlm_worker_regression

재실행 안전 — JSONL 누적, 이미 성공한 clip 은 skip (`already_done`).
processed 0 건이면 분석만 수행.

## 출력
- per-clip 진행 로그
- 최종: raw 정확도 / feeding-merged 정확도 / token sum / cost USD / floor 검증

## 비용 가격 (2026-05 기준 — Gemini 2.5 Flash)
- input: $0.30 / 1M tokens (영상/이미지 포함)
- output: $2.50 / 1M tokens

가격 변동 시 `PRICE_*` 상수만 수정.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import create_client

# project root path 확보 — `python -m scripts.X` 또는 `uv run python scripts/X.py` 양쪽 호환
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.vlm.gemini_client import (  # noqa: E402
    PERMANENT_ERRORS,
    TRANSIENT_ERRORS,
    VlmResponseInvalid,
    classify_clip,
    download_clip_bytes,
)
from backend.vlm.prompts import (  # noqa: E402
    build_system_prompt,
    map_db_species_to_code,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("eval_vlm_regression")

OUT_PATH = Path("/tmp/vlm-regression.jsonl")

# 신규 evidence셋 식별 prefix. r2_key 가 이걸로 시작하면 eval-0608 (44건).
# load_eval_set(203) 에서 이 prefix 를 빼면 기존 159 부분집합 복원 (load_eval_set_0608) — v3.5 비교용.
EVAL0608_PREFIX = "clips/eval-0608/"

# Gemini 2.5 Flash pricing (USD per 1M tokens, 2026-05)
PRICE_INPUT_PER_1M = 0.30
PRICE_OUTPUT_PER_1M = 2.50

# v3.5 락인 floor (feature-poc-vlm-web.md) — 159 기준 legacy. 203 통합 후엔 분모가 달라
# 직접 비교 불가: 203 에는 hand_feeding(OOD) 19건이 섞여 v3.5(클래스 없음)는 자동 미달.
# v3.5↔v3.6 비교는 OOD 분리 후 P0 부분에만 이 floor 적용 (eval_vlm_v36_handfeeding 참고).
FLOOR_RAW = 0.850  # 135/159 (legacy, P0 부분 참고용)
FLOOR_FEEDING_MERGED = 0.855  # 136/159 (legacy, P0 부분 참고용)

# feeding 통합 매핑 — `web/src/types.ts:UI_BEHAVIOR_CLASSES` 동치 (drinking + eating_paste → feeding).
FEEDING_MERGE = {"drinking": "feeding", "eating_paste": "feeding"}
HIDING_MERGE = {"hiding": "moving"}  # eval-only — 모션 트리거 데이터셋에 진짜 hiding 없음


def merge_label(action: str, *maps: dict[str, str]) -> str:
    out = action
    for m in maps:
        out = m.get(out, out)
    return out


@dataclass
class EvalRow:
    clip_id: str
    species_id: str | None
    r2_key: str
    gt_action: str


def load_eval_set() -> list[EvalRow]:
    """203건 통합 평가셋 = human GT + has_motion + r2_key 클립 전부 (159 + 44 eval-0608).

    2026-06-08 부터 159 동결 해제 — 신규 evidence셋도 함께 본다. 159 부분집합이
    필요하면 `load_eval_set_0608`(44)을 빼서 복원 (203 − 44 = 159).
    """
    load_dotenv(REPO_ROOT / ".env")
    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )

    # GT 클립 ID
    gt_rows: list[dict[str, Any]] = []
    off = 0
    while True:
        page = (
            sb.table("behavior_logs")
            .select("clip_id, action")
            .eq("source", "human")
            .range(off, off + 999)
            .execute()
            .data
        )
        if not page:
            break
        gt_rows.extend(page)
        if len(page) < 1000:
            break
        off += 1000
    # 한 클립에 human row 여러 개 → 마지막 라벨 사용 (PoC analyze 동치, GT 안정 가정)
    gt_map: dict[str, str] = {r["clip_id"]: r["action"] for r in gt_rows}

    # 클립 + species_id (LEFT JOIN pets via PostgREST embedding)
    clips: list[dict[str, Any]] = []
    off = 0
    while True:
        page = (
            sb.table("camera_clips")
            .select("id, r2_key, pets(species_id)")
            .eq("has_motion", True)
            .not_.is_("r2_key", None)
            .range(off, off + 999)
            .execute()
            .data
        )
        if not page:
            break
        clips.extend(page)
        if len(page) < 1000:
            break
        off += 1000

    targets: list[EvalRow] = []
    for c in clips:
        cid = c["id"]
        if cid not in gt_map:
            continue
        pets = c.get("pets")
        species = pets.get("species_id") if isinstance(pets, dict) else None
        targets.append(
            EvalRow(
                clip_id=cid,
                species_id=species,
                r2_key=c["r2_key"],
                gt_action=gt_map[cid],
            )
        )
    targets.sort(key=lambda r: r.clip_id)
    return targets


def load_eval_set_0608() -> list[EvalRow]:
    """eval-0608 신규 evidence셋 (44건) — r2_key prefix 로 식별, 159 동결셋과 분리.

    `load_eval_set`(159 화이트리스트) 과 독립. Gemini key 복구 후 v3.6 정량 평가에
    재사용 — `eval_vlm_v36_handfeeding` 에서 load_eval_set 대신 이 로더로 교체하면
    같은 인퍼런스 코드로 44건을 돌릴 수 있다 (지금은 Claude 정성 트랙으로 선검증).
    """
    load_dotenv(REPO_ROOT / ".env")
    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )

    gt_rows: list[dict[str, Any]] = []
    off = 0
    while True:
        page = (
            sb.table("behavior_logs")
            .select("clip_id, action")
            .eq("source", "human")
            .range(off, off + 999)
            .execute()
            .data
        )
        if not page:
            break
        gt_rows.extend(page)
        if len(page) < 1000:
            break
        off += 1000
    gt_map: dict[str, str] = {r["clip_id"]: r["action"] for r in gt_rows}

    clips: list[dict[str, Any]] = []
    off = 0
    while True:
        page = (
            sb.table("camera_clips")
            .select("id, r2_key, pets(species_id)")
            .like("r2_key", f"{EVAL0608_PREFIX}%")
            .range(off, off + 999)
            .execute()
            .data
        )
        if not page:
            break
        clips.extend(page)
        if len(page) < 1000:
            break
        off += 1000

    targets: list[EvalRow] = []
    for c in clips:
        cid = c["id"]
        if cid not in gt_map:
            continue
        pets = c.get("pets")
        species = pets.get("species_id") if isinstance(pets, dict) else None
        targets.append(
            EvalRow(
                clip_id=cid,
                species_id=species,
                r2_key=c["r2_key"],
                gt_action=gt_map[cid],
            )
        )
    targets.sort(key=lambda r: r.clip_id)
    return targets


def already_done() -> set[str]:
    if not OUT_PATH.exists():
        return set()
    done: set[str] = set()
    for line in OUT_PATH.read_text().splitlines():
        try:
            r = json.loads(line)
            if r.get("ok"):
                done.add(r["clip_id"])
        except json.JSONDecodeError:
            continue
    return done


def run_inference(targets: list[EvalRow]) -> None:
    done = already_done()
    pending = [t for t in targets if t.clip_id not in done]
    logger.info(
        "평가셋 %d건, 완료 %d, 잔여 %d", len(targets), len(done), len(pending)
    )
    if not pending:
        logger.info("처리할 클립 없음 — 분석으로 넘어감")
        return

    t0 = time.time()
    ok = 0
    fail = 0
    with OUT_PATH.open("a") as f:
        for i, target in enumerate(pending, 1):
            species = map_db_species_to_code(target.species_id)
            sys_prompt = build_system_prompt(species)

            try:
                video_bytes = download_clip_bytes(target.r2_key)
            except Exception as exc:
                rec = {
                    "clip_id": target.clip_id,
                    "ok": False,
                    "error": f"r2_download: {exc!s}"[:500],
                }
                f.write(json.dumps(rec) + "\n")
                f.flush()
                fail += 1
                logger.warning(
                    "[%d/%d] %s R2 download FAIL: %s",
                    i,
                    len(pending),
                    target.clip_id[:8],
                    exc,
                )
                continue

            t_call = time.time()
            try:
                result = classify_clip(
                    video_bytes=video_bytes, system_prompt=sys_prompt
                )
            except TRANSIENT_ERRORS as exc:
                rec = {
                    "clip_id": target.clip_id,
                    "ok": False,
                    "error": f"transient: {type(exc).__name__}: {exc!s}"[:500],
                }
                f.write(json.dumps(rec) + "\n")
                f.flush()
                fail += 1
                logger.warning(
                    "[%d/%d] %s transient: %s — JSONL 에 fail 기록 (재실행 시 retry)",
                    i,
                    len(pending),
                    target.clip_id[:8],
                    type(exc).__name__,
                )
                continue
            except (PERMANENT_ERRORS + (VlmResponseInvalid,)) as exc:
                rec = {
                    "clip_id": target.clip_id,
                    "ok": False,
                    "error": f"permanent: {type(exc).__name__}: {exc!s}"[:500],
                }
                f.write(json.dumps(rec) + "\n")
                f.flush()
                fail += 1
                logger.error(
                    "[%d/%d] %s permanent: %s",
                    i,
                    len(pending),
                    target.clip_id[:8],
                    type(exc).__name__,
                )
                continue

            elapsed_ms = int((time.time() - t_call) * 1000)
            rec = {
                "clip_id": target.clip_id,
                "ok": True,
                "action": result.action,
                "confidence": result.confidence,
                "reasoning": result.reasoning,
                "tokens_input": result.tokens_input,
                "tokens_output": result.tokens_output,
                "elapsed_ms": elapsed_ms,
                "model_id": result.model_id,
                "gt_action": target.gt_action,
                "species_id": target.species_id,
            }
            f.write(json.dumps(rec) + "\n")
            f.flush()
            ok += 1
            logger.info(
                "[%d/%d] %s → %-14s conf=%.2f tok=%s/%s (%dms) GT=%s",
                i,
                len(pending),
                target.clip_id[:8],
                result.action,
                result.confidence,
                result.tokens_input,
                result.tokens_output,
                elapsed_ms,
                target.gt_action,
            )

    logger.info(
        "인퍼런스 완료 — ok=%d fail=%d (%.0fs)", ok, fail, time.time() - t0
    )


def analyze() -> None:
    """JSONL 결과 → 정확도 + 비용. 159건 모두 성공 가정 (실패 있으면 skip 후 보고)."""
    if not OUT_PATH.exists():
        logger.error("결과 파일 없음 — 인퍼런스 먼저 실행: %s", OUT_PATH)
        return

    rows: list[dict[str, Any]] = []
    failed_count = 0
    for line in OUT_PATH.read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("ok"):
            rows.append(rec)
        else:
            failed_count += 1

    n = len(rows)
    if n == 0:
        logger.error("성공 결과 0 — 분석 불가")
        return

    correct_raw = 0
    correct_feeding = 0
    tok_in = 0
    tok_out = 0
    by_gt: dict[str, dict[str, int]] = {}  # GT → {correct, total}
    confusion: list[tuple[str, str, str]] = []  # (clip_id, gt, pred) 오답

    for r in rows:
        gt = r["gt_action"]
        pred = r["action"]
        gt_merged = merge_label(gt, HIDING_MERGE, FEEDING_MERGE)
        pred_merged = merge_label(pred, FEEDING_MERGE)
        bucket = by_gt.setdefault(gt, {"correct": 0, "total": 0})
        bucket["total"] += 1
        if gt == pred:
            correct_raw += 1
            bucket["correct"] += 1
        if gt_merged == pred_merged:
            correct_feeding += 1
        else:
            confusion.append((r["clip_id"], gt_merged, pred_merged))
        tok_in += r.get("tokens_input") or 0
        tok_out += r.get("tokens_output") or 0

    raw_acc = correct_raw / n
    feeding_acc = correct_feeding / n
    cost = (
        tok_in * PRICE_INPUT_PER_1M / 1_000_000
        + tok_out * PRICE_OUTPUT_PER_1M / 1_000_000
    )

    print()
    print("=" * 60)
    print(f"평가 요약 — N={n} (실패 {failed_count})")
    print("=" * 60)
    print(f"raw 정확도          : {correct_raw}/{n} = {raw_acc:.3%}  (floor {FLOOR_RAW:.1%})")
    print(f"feeding-merged 정확도: {correct_feeding}/{n} = {feeding_acc:.3%}  (floor {FLOOR_FEEDING_MERGED:.1%})")
    print(f"tokens input/output : {tok_in:,} / {tok_out:,}")
    print(f"비용 (Gemini 2.5 Flash): ${cost:.4f}")
    print()

    print("GT 분포 + per-class 정확도 (raw):")
    for gt in sorted(by_gt):
        b = by_gt[gt]
        acc = b["correct"] / b["total"] if b["total"] else 0
        print(f"  {gt:14s} {b['correct']:3d}/{b['total']:3d} = {acc:.1%}")
    print()

    if confusion:
        print(f"feeding-merged 오답 {len(confusion)}건:")
        for cid, gt_m, pred_m in confusion[:30]:
            print(f"  {cid[:8]} GT={gt_m:8s} → pred={pred_m}")
        if len(confusion) > 30:
            print(f"  ... +{len(confusion) - 30}건")
        print()

    # Floor 검증
    print("=" * 60)
    print("Floor 검증 (v3.5 production 락인)")
    print("=" * 60)
    if feeding_acc >= FLOOR_FEEDING_MERGED:
        print(f"  ✅ feeding-merged {feeding_acc:.3%} >= floor {FLOOR_FEEDING_MERGED:.1%}")
    else:
        print(f"  ❌ feeding-merged {feeding_acc:.3%} < floor {FLOOR_FEEDING_MERGED:.1%} — 롤백 검토")
    if raw_acc >= FLOOR_RAW:
        print(f"  ✅ raw {raw_acc:.3%} >= floor {FLOOR_RAW:.1%}")
    else:
        print(f"  ⚠️ raw {raw_acc:.3%} < floor {FLOOR_RAW:.1%}")


def main() -> int:
    targets = load_eval_set()
    if len(targets) != 203:
        logger.warning("평가셋 크기 %d (203 통합 가정 — 159 + 44 eval-0608) — DB 상태 확인", len(targets))
    run_inference(targets)
    analyze()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
