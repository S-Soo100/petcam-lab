"""Mac mini local Track A 159건 평가.

production DB에는 쓰지 않는다. Supabase/R2는 read-only로 평가셋과 mp4를 읽고,
Ollama 결과는 `storage/local-track-a/eval/*.jsonl` artifact로만 남긴다.

실행:
    uv run python scripts/eval_local_track_a.py --limit 5
    uv run python scripts/eval_local_track_a.py
    uv run python scripts/eval_local_track_a.py --force
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import create_client

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.local_track_a import (  # noqa: E402
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_OUTPUT_DIR,
    LocalTrackAError,
    analyze_clip_file,
    download_r2_clip_to_temp,
)
from backend.vlm.prompts import map_db_species_to_code  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("eval_local_track_a")

DEFAULT_EVAL_DIR = DEFAULT_OUTPUT_DIR / "eval"
DEFAULT_OUT_PATH = DEFAULT_EVAL_DIR / "local-track-a-eval.jsonl"

# v3.5 Gemini production baseline. local Track A는 아직 gate가 아니라 비교 기준.
BASELINE_RAW = 0.850
BASELINE_FEEDING_MERGED = 0.855

FEEDING_MERGE = {"drinking": "feeding", "eating_paste": "feeding"}
HIDING_MERGE = {"hiding": "moving"}


@dataclass(frozen=True, slots=True)
class EvalRow:
    clip_id: str
    species_id: str | None
    r2_key: str
    gt_action: str


def merge_label(action: str, *maps: dict[str, str]) -> str:
    out = action
    for mapping in maps:
        out = mapping.get(out, out)
    return out


def load_eval_set() -> list[EvalRow]:
    """human GT + motion + R2 key가 있는 Track A keep-set 로드."""
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
    for clip in clips:
        clip_id = clip["id"]
        if clip_id not in gt_map:
            continue
        pets = clip.get("pets")
        species_id = pets.get("species_id") if isinstance(pets, dict) else None
        targets.append(
            EvalRow(
                clip_id=clip_id,
                species_id=species_id,
                r2_key=clip["r2_key"],
                gt_action=gt_map[clip_id],
            )
        )
    targets.sort(key=lambda row: row.clip_id)
    return targets


def already_done(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    done: set[str] = set()
    for line in out_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("ok"):
            done.add(str(rec["clip_id"]))
    return done


def run_inference(
    targets: list[EvalRow],
    *,
    out_path: Path,
    artifact_dir: Path,
    model: str,
    ollama_url: str,
    sample_fps: float,
    max_frames: int,
    thumb_width: int,
    timeout_sec: int,
    force: bool,
) -> None:
    if force and out_path.exists():
        out_path.unlink()

    done = already_done(out_path)
    pending = [target for target in targets if target.clip_id not in done]
    logger.info("평가셋 %d건, 완료 %d, 잔여 %d", len(targets), len(done), len(pending))
    if not pending:
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    started_all = time.monotonic()
    ok = 0
    fail = 0

    with out_path.open("a", encoding="utf-8") as f:
        for index, target in enumerate(pending, 1):
            started = time.monotonic()
            species = map_db_species_to_code(target.species_id)
            tmp_path: Path | None = None
            try:
                tmp_path = download_r2_clip_to_temp(target.r2_key)
                result = analyze_clip_file(
                    tmp_path,
                    clip_id=target.clip_id,
                    output_dir=artifact_dir,
                    model=model,
                    ollama_url=ollama_url,
                    species=species,
                    sample_fps=sample_fps,
                    max_frames=max_frames,
                    thumb_width=thumb_width,
                    timeout_sec=timeout_sec,
                )
                rec = {
                    "ok": True,
                    "gt_action": target.gt_action,
                    "species_id": target.species_id,
                    "r2_key": target.r2_key,
                    **asdict(result),
                }
                ok += 1
                logger.info(
                    "[%d/%d] %s → %-14s conf=%.2f %.1fs GT=%s",
                    index,
                    len(pending),
                    target.clip_id[:8],
                    result.label,
                    result.confidence,
                    time.monotonic() - started,
                    target.gt_action,
                )
            except Exception as exc:  # noqa: BLE001 — batch는 계속 진행해야 함
                rec = {
                    "ok": False,
                    "clip_id": target.clip_id,
                    "gt_action": target.gt_action,
                    "species_id": target.species_id,
                    "r2_key": target.r2_key,
                    "error": f"{type(exc).__name__}: {exc!s}"[:500],
                }
                fail += 1
                logger.warning(
                    "[%d/%d] %s FAIL: %s",
                    index,
                    len(pending),
                    target.clip_id[:8],
                    rec["error"],
                )
            finally:
                if tmp_path is not None:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        pass

            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()

    logger.info(
        "local eval inference 완료 — ok=%d fail=%d elapsed=%.1fs",
        ok,
        fail,
        time.monotonic() - started_all,
    )


def analyze(out_path: Path) -> dict[str, Any] | None:
    if not out_path.exists():
        logger.error("결과 파일 없음: %s", out_path)
        return None

    rows: list[dict[str, Any]] = []
    failed_count = 0
    for line in out_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("ok"):
            rows.append(rec)
        else:
            failed_count += 1

    if not rows:
        logger.error("성공 결과 0 — 분석 불가")
        return None

    correct_raw = 0
    correct_feeding = 0
    needs_review = 0
    latency_sum = 0.0
    latencies: list[float] = []
    by_gt: dict[str, dict[str, int]] = {}
    by_pred: dict[str, int] = {}
    confusion: list[tuple[str, str, str]] = []

    for row in rows:
        gt = row["gt_action"]
        pred = row["label"]
        gt_merged = merge_label(gt, HIDING_MERGE, FEEDING_MERGE)
        pred_merged = merge_label(pred, FEEDING_MERGE)
        bucket = by_gt.setdefault(gt, {"correct": 0, "total": 0})
        bucket["total"] += 1
        by_pred[pred] = by_pred.get(pred, 0) + 1
        if gt == pred:
            correct_raw += 1
            bucket["correct"] += 1
        if gt_merged == pred_merged:
            correct_feeding += 1
        else:
            confusion.append((row["clip_id"], gt_merged, pred_merged))
        if row.get("needs_review"):
            needs_review += 1
        latency = float(row.get("latency_sec") or 0)
        latency_sum += latency
        latencies.append(latency)

    n = len(rows)
    raw_acc = correct_raw / n
    feeding_acc = correct_feeding / n
    avg_latency = latency_sum / n
    sorted_latencies = sorted(latencies)
    p50_latency = sorted_latencies[int((n - 1) * 0.50)]
    p95_latency = sorted_latencies[int((n - 1) * 0.95)]
    max_latency = sorted_latencies[-1]
    needs_review_rate = needs_review / n
    summary = {
        "n": n,
        "failed_count": failed_count,
        "correct_raw": correct_raw,
        "raw_acc": raw_acc,
        "correct_feeding_merged": correct_feeding,
        "feeding_merged_acc": feeding_acc,
        "needs_review": needs_review,
        "needs_review_rate": needs_review_rate,
        "avg_latency_sec": avg_latency,
        "p50_latency_sec": p50_latency,
        "p95_latency_sec": p95_latency,
        "max_latency_sec": max_latency,
        "estimated_50_clips_min": avg_latency * 50 / 60,
        "estimated_100_clips_min": avg_latency * 100 / 60,
        "baseline_raw": BASELINE_RAW,
        "baseline_feeding_merged": BASELINE_FEEDING_MERGED,
        "pred_distribution": by_pred,
    }

    print()
    print("=" * 72)
    print(f"local Track A 평가 요약 — N={n} (실패 {failed_count})")
    print("=" * 72)
    print(f"raw 정확도             : {correct_raw}/{n} = {raw_acc:.3%}  (Gemini floor {BASELINE_RAW:.1%})")
    print(f"feeding-merged 정확도  : {correct_feeding}/{n} = {feeding_acc:.3%}  (Gemini floor {BASELINE_FEEDING_MERGED:.1%})")
    print(f"needs_review           : {needs_review}/{n} = {needs_review_rate:.3%}")
    print(f"latency avg/p50/p95/max: {avg_latency:.2f}s / {p50_latency:.2f}s / {p95_latency:.2f}s / {max_latency:.2f}s")
    print(f"batch estimate         : 50 clips {avg_latency * 50 / 60:.1f}m / 100 clips {avg_latency * 100 / 60:.1f}m")
    print()

    print("예측 분포:")
    for pred in sorted(by_pred):
        print(f"  {pred:14s} {by_pred[pred]:3d}/{n:3d} = {by_pred[pred] / n:.1%}")
    print()

    print("GT 분포 + per-class 정확도 (raw):")
    for gt in sorted(by_gt):
        bucket = by_gt[gt]
        acc = bucket["correct"] / bucket["total"] if bucket["total"] else 0
        print(f"  {gt:14s} {bucket['correct']:3d}/{bucket['total']:3d} = {acc:.1%}")
    print()

    if confusion:
        print(f"feeding-merged 오답 {len(confusion)}건:")
        for clip_id, gt_merged, pred_merged in confusion[:40]:
            print(f"  {clip_id[:8]} GT={gt_merged:10s} → pred={pred_merged}")
        if len(confusion) > 40:
            print(f"  ... +{len(confusion) - 40}건")
        print()

    print("=" * 72)
    print("Gemini v3.5 baseline 비교")
    print("=" * 72)
    raw_delta = raw_acc - BASELINE_RAW
    feeding_delta = feeding_acc - BASELINE_FEEDING_MERGED
    print(f"  raw delta            : {raw_delta:+.3%}")
    print(f"  feeding-merged delta : {feeding_delta:+.3%}")
    if feeding_acc >= BASELINE_FEEDING_MERGED:
        print("  ✅ local Track A가 feeding-merged baseline 이상")
    else:
        print("  ❌ local Track A가 feeding-merged baseline 미달")

    summary_path = out_path.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nsummary: {summary_path}")
    return summary


def _parse_args() -> argparse.Namespace:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(description="Mac mini local Track A eval")
    parser.add_argument("--limit", type=int, help="앞 N건만 smoke/eval")
    parser.add_argument("--force", action="store_true", help="기존 JSONL 삭제 후 재실행")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_EVAL_DIR / "artifacts")
    parser.add_argument("--model", default=os.getenv("LOCAL_TRACK_A_MODEL", DEFAULT_MODEL))
    parser.add_argument(
        "--ollama-url",
        default=os.getenv("LOCAL_TRACK_A_OLLAMA_URL", DEFAULT_OLLAMA_URL),
    )
    parser.add_argument(
        "--sample-fps",
        type=float,
        default=float(os.getenv("LOCAL_TRACK_A_SAMPLE_FPS", "1.0")),
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=int(os.getenv("LOCAL_TRACK_A_MAX_FRAMES", "60")),
    )
    parser.add_argument(
        "--thumb-width",
        type=int,
        default=int(os.getenv("LOCAL_TRACK_A_THUMB_WIDTH", "320")),
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=int(os.getenv("LOCAL_TRACK_A_TIMEOUT_SEC", "180")),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    targets = load_eval_set()
    if len(targets) != 159:
        logger.warning("평가셋 크기 %d (159 keep-set 가정)", len(targets))
    if args.limit is not None:
        targets = targets[: args.limit]

    try:
        run_inference(
            targets,
            out_path=args.out,
            artifact_dir=args.artifact_dir,
            model=args.model,
            ollama_url=args.ollama_url,
            sample_fps=args.sample_fps,
            max_frames=args.max_frames,
            thumb_width=args.thumb_width,
            timeout_sec=args.timeout_sec,
            force=args.force,
        )
    except LocalTrackAError:
        logger.exception("local Track A 설정/호출 오류")
        return 1
    analyze(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
