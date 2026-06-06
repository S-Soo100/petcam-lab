"""v3.6 후보 (hand_feeding OOD) 회귀평가 — feature-hand-feeding-ood-label.md C-3.

production 가드 `eval_vlm_worker_regression.py` 의 load_eval_set / 가격상수 / merge 를
재사용하고, prompt_version="v3.6" 을 주입한다. production v3.5 가드와 결과 분리
(`/tmp/vlm-regression-v36.jsonl`). **GT sync(6건) 후 실행** — eval GT 가 새 값이라야
v3.6 의 hand_feeding 탐지가 공정하게 평가됨.

분석은 159건을 두 그룹으로 분리:
- **P0/기타** (GT 가 hand_feeding 아님): feeding-merged 정확도 → v3.5 floor 85.5% 와
  근사 비교 (분모가 159가 아니라 ~153 이라 직접 비교 아님 — 추세 판단용).
- **OOD** (GT=hand_feeding): v3.6 가 hand_feeding 으로 잡은 비율 (recall). v3.5 는
  클래스 자체가 없어 구조적으로 0 → v3.6 의 순수 이득.

재실행 안전 (JSONL 누적, 성공 clip skip).

실행: PYTHONPATH=. uv run python scripts/eval_vlm_v36_handfeeding.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

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
from backend.vlm.prompts import build_system_prompt, map_db_species_to_code  # noqa: E402
from scripts.eval_vlm_worker_regression import (  # noqa: E402
    FEEDING_MERGE,
    HIDING_MERGE,
    PRICE_INPUT_PER_1M,
    PRICE_OUTPUT_PER_1M,
    load_eval_set,
    merge_label,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("eval_v36")

OUT_PATH = Path("/tmp/vlm-regression-v36.jsonl")
PROMPT_VERSION = "v3.6"
FLOOR_FEEDING_MERGED = 0.855  # v3.5 락인 (옛 159건 GT 기준 — 분모 다름 감안 근사 비교)


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


def run_inference(targets) -> None:
    done = already_done()
    pending = [t for t in targets if t.clip_id not in done]
    logger.info(
        "평가셋 %d, 완료 %d, 잔여 %d (prompt=%s)",
        len(targets),
        len(done),
        len(pending),
        PROMPT_VERSION,
    )
    if not pending:
        logger.info("처리할 클립 없음 — 분석으로")
        return

    ok = fail = 0
    t0 = time.time()
    with OUT_PATH.open("a") as f:
        for i, t in enumerate(pending, 1):
            species = map_db_species_to_code(t.species_id)
            sys_prompt = build_system_prompt(species, prompt_version=PROMPT_VERSION)
            try:
                video_bytes = download_clip_bytes(t.r2_key)
                result = classify_clip(video_bytes=video_bytes, system_prompt=sys_prompt)
            except TRANSIENT_ERRORS as exc:
                rec = {"clip_id": t.clip_id, "ok": False, "error": f"transient: {type(exc).__name__}"}
                f.write(json.dumps(rec) + "\n")
                f.flush()
                fail += 1
                logger.warning("[%d/%d] %s transient %s", i, len(pending), t.clip_id[:8], type(exc).__name__)
                continue
            except (PERMANENT_ERRORS + (VlmResponseInvalid,)) as exc:
                rec = {"clip_id": t.clip_id, "ok": False, "error": f"permanent: {type(exc).__name__}: {exc!s}"[:300]}
                f.write(json.dumps(rec) + "\n")
                f.flush()
                fail += 1
                logger.error("[%d/%d] %s permanent %s", i, len(pending), t.clip_id[:8], type(exc).__name__)
                continue
            except Exception as exc:  # noqa: BLE001 — r2 download 등
                rec = {"clip_id": t.clip_id, "ok": False, "error": f"other: {type(exc).__name__}: {exc!s}"[:300]}
                f.write(json.dumps(rec) + "\n")
                f.flush()
                fail += 1
                logger.warning("[%d/%d] %s other %s", i, len(pending), t.clip_id[:8], type(exc).__name__)
                continue

            rec = {
                "clip_id": t.clip_id,
                "ok": True,
                "action": result.action,
                "confidence": result.confidence,
                "reasoning": result.reasoning,
                "tokens_input": result.tokens_input,
                "tokens_output": result.tokens_output,
                "gt_action": t.gt_action,
                "species_id": t.species_id,
            }
            f.write(json.dumps(rec) + "\n")
            f.flush()
            ok += 1
            logger.info(
                "[%d/%d] %s → %-14s conf=%.2f GT=%s",
                i,
                len(pending),
                t.clip_id[:8],
                result.action,
                result.confidence,
                t.gt_action,
            )
    logger.info("인퍼런스 완료 ok=%d fail=%d (%.0fs)", ok, fail, time.time() - t0)


def analyze() -> None:
    if not OUT_PATH.exists():
        logger.error("결과 파일 없음: %s", OUT_PATH)
        return

    rows = []
    failed = 0
    for line in OUT_PATH.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("ok"):
            rows.append(r)
        else:
            failed += 1

    n = len(rows)
    if not n:
        logger.error("성공 결과 0")
        return

    p0_total = p0_correct = 0
    ood_total = ood_recovered = 0
    tok_in = tok_out = 0
    confusion = []
    ood_detail = []

    for r in rows:
        gt, pred = r["gt_action"], r["action"]
        tok_in += r.get("tokens_input") or 0
        tok_out += r.get("tokens_output") or 0
        if gt == "hand_feeding":
            ood_total += 1
            if pred == "hand_feeding":
                ood_recovered += 1
            ood_detail.append((r["clip_id"], pred))
            continue
        gt_m = merge_label(gt, HIDING_MERGE, FEEDING_MERGE)
        pred_m = merge_label(pred, FEEDING_MERGE)
        p0_total += 1
        if gt_m == pred_m:
            p0_correct += 1
        else:
            confusion.append((r["clip_id"], gt_m, pred_m))

    p0_acc = p0_correct / p0_total if p0_total else 0.0
    ood_recall = ood_recovered / ood_total if ood_total else 0.0
    cost = tok_in * PRICE_INPUT_PER_1M / 1_000_000 + tok_out * PRICE_OUTPUT_PER_1M / 1_000_000

    print("\n" + "=" * 64)
    print(f"v3.6 후보 평가 — N={n} (실패 {failed})  [prompt={PROMPT_VERSION}]")
    print("=" * 64)
    print(f"P0/기타 feeding-merged : {p0_correct}/{p0_total} = {p0_acc:.3%}")
    print(f"  (v3.5 floor {FLOOR_FEEDING_MERGED:.1%} — 분모 159→{p0_total} 라 직접 비교 아닌 근사)")
    print(f"OOD hand_feeding recall: {ood_recovered}/{ood_total} = {ood_recall:.1%}  (v3.5 는 구조적 0)")
    print(f"비용 (Gemini 2.5 Flash): ${cost:.4f}  (tokens {tok_in:,}/{tok_out:,})")
    print()
    if ood_detail:
        print("OOD 6건 v3.6 예측:")
        for cid, pred in ood_detail:
            mark = "✅" if pred == "hand_feeding" else "❌"
            print(f"  {mark} {cid[:8]} → {pred}")
        print()
    if confusion:
        print(f"P0/기타 오답 {len(confusion)}건:")
        for cid, g, p in confusion[:30]:
            print(f"  {cid[:8]} GT={g:12s} → {p}")
        if len(confusion) > 30:
            print(f"  ... +{len(confusion) - 30}건")
        print()
    print("=" * 64)
    print("판정 (feature-hand-feeding-ood-label.md C-3 완료조건)")
    print("=" * 64)
    if p0_acc >= FLOOR_FEEDING_MERGED:
        print(f"  ✅ P0 floor: {p0_acc:.3%} >= {FLOOR_FEEDING_MERGED:.1%} (근사)")
    else:
        print(f"  ⚠️ P0 floor: {p0_acc:.3%} < {FLOOR_FEEDING_MERGED:.1%} — broken 확인 + 롤백 검토")
    print(f"  OOD 탐지: hand_feeding {ood_recovered}/{ood_total} (recovered>broken 여부 수동 판단)")


def main() -> int:
    targets = load_eval_set()
    if len(targets) != 159:
        logger.warning("평가셋 %d (159 가정)", len(targets))
    run_inference(targets)
    analyze()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
