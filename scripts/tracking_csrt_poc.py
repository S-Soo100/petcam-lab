"""Tracking PoC — CSRT 트래커로 도마뱀 bbox 시계열 추출.

흐름:
1. clips-gate.txt 에서 clip_id (인자 `--clip <id>` 없으면 첫 게이트 클립)
2. Supabase 에서 r2_key 조회 → R2 에서 영상 bytes 다운로드
3. 첫 프레임 추출 → OWLv2 (로컬 transformers) zero-shot detection 으로 gecko bbox
4. CSRT 트래커 초기화 → 전체 프레임 루프 → bbox 시계열
5. trajectories/{clip_id}.json + trajectories/{clip_id}_init.jpg (첫 프레임 bbox 시각화) 저장

학습 노트:
- OpenCV TrackerCSRT: Discriminative Correlation Filter + spatial reliability map.
  OpenCV 4.5+ 부터 contrib 모듈에 들어가서 `opencv-contrib-python-headless` 패키지 필요
  (메인 `opencv-python-headless` 에는 MIL / DaSiamRPN / GOTURN / Nano / Vit 만 있음).
- OWLv2 (google/owlv2-base-patch16-ensemble): open-vocabulary object detection.
  자연어 prompt ("a gecko") 로 zero-shot bbox 검출. 원래 HuggingFace Inference API 로
  호출하려 했지만 hf-inference 무료 endpoint 가 OWLv2/GroundingDINO 같은 small vision
  모델을 더 이상 호스팅 안 함 (api-inference 404, router 401) → 로컬 transformers 로
  전환. 첫 호출 시 ~600MB 가중치 다운로드 후 ~/.cache/huggingface 캐시. M-시리즈는
  MPS GPU 사용. PoC 40건 + 향후 작업까지 한 번 다운로드로 커버.

참고: specs/experiment-tracking-vlm-input.md
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from dotenv import load_dotenv
from PIL import Image

# 직접 실행 + `from backend.*` 절대 import 호환
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from backend.supabase_client import get_supabase_client  # noqa: E402
from backend.vlm.gemini_client import download_clip_bytes  # noqa: E402

GATE_PATH = ROOT / "experiments/tracking-poc/clips-gate.txt"
TRAJ_DIR = ROOT / "experiments/tracking-poc/trajectories"
TRAJ_DIR.mkdir(parents=True, exist_ok=True)

OWLV2_MODEL_ID = "google/owlv2-base-patch16-ensemble"
PROMPTS = ["a gecko", "a lizard"]
# OWLv2 는 score 가 0.05~0.3 범위로 낮음 (DETR 처럼 학습된 게 아니라 image-text matching).
# threshold 가 너무 높으면 작은 도마뱀 미검출, 너무 낮으면 배경 false positive.
DETECTION_THRESHOLD = 0.10
# bbox sanity: 프레임 면적 대비 비율 — OWLv2 가 종종 "프레임 전체" 를 high-score 로 잡음.
# 그건 tracker 학습에 무용 (배경 패턴만 잡힘) → 거름.
BBOX_AREA_MIN_RATIO = 0.005  # 0.5%
BBOX_AREA_MAX_RATIO = 0.3  # 30% — OWLv2 가 "사육장 절반" 을 high-score 로 잡는 경향 (실측)

_owlv2_cache: tuple | None = None  # (processor, model, device)


def first_clip_id() -> str:
    """게이트셋 첫 데이터 라인의 clip_id (헤더/주석 skip)."""
    with GATE_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            return line.split("\t")[0]
    raise RuntimeError(f"no clip in {GATE_PATH}")


def fetch_r2_key(clip_id: str) -> str:
    sb = get_supabase_client()
    res = (
        sb.table("camera_clips")
        .select("r2_key")
        .eq("id", clip_id)
        .single()
        .execute()
    )
    if not res.data or not res.data.get("r2_key"):
        raise RuntimeError(f"r2_key not found for clip {clip_id}")
    return res.data["r2_key"]


def extract_first_frame(video_path: Path) -> tuple[np.ndarray, float]:
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    ret, frame = cap.read()
    cap.release()
    if not ret:
        raise RuntimeError("첫 프레임 추출 실패")
    return frame, fps


def _load_owlv2() -> tuple:
    """OWLv2 processor + model + device 로드 (모듈 캐시).

    transformers 가 무거운 import 라 main() 진입 후 첫 detect 시점에만 로드.
    """
    global _owlv2_cache
    if _owlv2_cache is not None:
        return _owlv2_cache
    print(f"[owlv2] loading {OWLV2_MODEL_ID} (첫 호출이면 ~600MB 다운로드)...")
    t0 = time.time()
    import torch
    from transformers import Owlv2ForObjectDetection, Owlv2Processor

    processor = Owlv2Processor.from_pretrained(OWLV2_MODEL_ID)
    model = Owlv2ForObjectDetection.from_pretrained(OWLV2_MODEL_ID)

    if torch.backends.mps.is_available():
        device = "mps"
    elif torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"
    model = model.to(device).eval()
    print(f"  loaded on {device} ({time.time() - t0:.1f}s)")
    _owlv2_cache = (processor, model, device)
    return _owlv2_cache


def zero_shot_detect(image_bytes: bytes, prompts: list[str]) -> list[dict]:
    """OWLv2 로컬 zero-shot object detection.

    응답 포맷은 HF Inference API 와 동일하게 맞춰서 호출부 변경 없게:
        [{"score": float, "label": str, "box": {xmin,ymin,xmax,ymax}}]
    """
    import torch

    processor, model, device = _load_owlv2()
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    inputs = processor(images=img, text=[prompts], return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs)
    # post_process: (height, width) 순서로 target_size
    target_sizes = torch.tensor([[img.size[1], img.size[0]]]).to(device)
    results = processor.post_process_grounded_object_detection(
        outputs=outputs,
        threshold=DETECTION_THRESHOLD,
        target_sizes=target_sizes,
        text_labels=[prompts],
    )[0]

    out = []
    for score, label, box in zip(
        results["scores"], results["text_labels"], results["boxes"], strict=False
    ):
        xmin, ymin, xmax, ymax = (float(v) for v in box.cpu().tolist())
        out.append(
            {
                "score": float(score.cpu()),
                "label": label,
                "box": {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
            }
        )
    out.sort(key=lambda d: d["score"], reverse=True)
    return out


def run_csrt(
    video_path: Path, init_bbox_xywh: tuple
) -> tuple[list[dict], dict]:
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    tracker = cv2.TrackerCSRT_create()
    ret, frame = cap.read()
    if not ret:
        cap.release()
        raise RuntimeError("video open failed")
    tracker.init(frame, init_bbox_xywh)
    trajectory = [{"frame": 0, "ok": True, "bbox_xywh": list(init_bbox_xywh)}]
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        idx += 1
        ok, bbox = tracker.update(frame)
        trajectory.append(
            {
                "frame": idx,
                "ok": bool(ok),
                "bbox_xywh": [float(b) for b in bbox] if ok else None,
            }
        )
    cap.release()
    return trajectory, {"fps": fps, "size": [w, h], "frame_count_meta": total}


def draw_init_viz(frame: np.ndarray, bbox_xywh: tuple, label: str, score: float) -> np.ndarray:
    vis = frame.copy()
    x, y, w_bb, h_bb = (int(round(v)) for v in bbox_xywh)
    cv2.rectangle(vis, (x, y), (x + w_bb, y + h_bb), (0, 255, 0), 2)
    cv2.putText(
        vis,
        f"{label} {score:.2f}",
        (x, max(15, y - 5)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 255, 0),
        2,
    )
    return vis


def read_gate_clips() -> list[str]:
    ids = []
    with GATE_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ids.append(line.split("\t")[0])
    return ids


def read_frame_at(video_path: Path, frame_idx: int) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None


def process_clip(clip_id: str, *, verbose: bool = True) -> dict:
    """단일 클립 tracking. 결과 dict 반환.

    status 값: ok / no_detection / no_valid_bbox / error
    """
    log = print if verbose else (lambda *a, **k: None)
    result: dict = {"clip_id": clip_id}
    log(f"\n[clip] {clip_id}")

    try:
        r2_key = fetch_r2_key(clip_id)
        log(f"  r2_key: {r2_key}")
        t0 = time.time()
        video_bytes = download_clip_bytes(r2_key)
        log(f"  {len(video_bytes) / 1024 / 1024:.2f} MB ({time.time() - t0:.2f}s)")

        tmp_video = TRAJ_DIR / f".tmp_{clip_id}.mp4"
        tmp_video.write_bytes(video_bytes)
        try:
            frame, fps = extract_first_frame(tmp_video)
            h, w = frame.shape[:2]
            log(f"  frame: {w}x{h}, fps={fps:.2f}")

            ok, jpg_buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            assert ok

            t0 = time.time()
            dets = zero_shot_detect(jpg_buf.tobytes(), PROMPTS)
            det_elapsed = time.time() - t0
            log(f"  detect: {det_elapsed:.2f}s, {len(dets)} dets")

            if not dets:
                result["status"] = "no_detection"
                return result

            frame_area = w * h
            area_min = frame_area * BBOX_AREA_MIN_RATIO
            area_max = frame_area * BBOX_AREA_MAX_RATIO
            for d in dets:
                b = d["box"]
                d["_area"] = (b["xmax"] - b["xmin"]) * (b["ymax"] - b["ymin"])
            valid = [d for d in dets if area_min <= d["_area"] <= area_max]
            if not valid:
                result["status"] = "no_valid_bbox"
                result["raw_areas_ratio"] = [d["_area"] / frame_area for d in dets]
                log(
                    f"  [!] sanity filter 통과 없음 — area_ratios: "
                    f"{[f'{r:.1%}' for r in result['raw_areas_ratio']]}"
                )
                return result

            top = max(valid, key=lambda d: d["score"])
            box = top["box"]
            xywh = (
                float(box["xmin"]),
                float(box["ymin"]),
                float(box["xmax"] - box["xmin"]),
                float(box["ymax"] - box["ymin"]),
            )
            area_ratio = top["_area"] / frame_area
            log(
                f"  pick: score={top['score']:.3f}, area_ratio={area_ratio:.1%}, "
                f"bbox_xywh={tuple(round(v, 1) for v in xywh)}"
            )

            # 첫 프레임 viz
            viz_init = draw_init_viz(frame, xywh, top["label"], top["score"])
            cv2.imwrite(str(TRAJ_DIR / f"{clip_id}_init.jpg"), viz_init)

            init_bbox_int = tuple(int(round(v)) for v in xywh)
            t0 = time.time()
            trajectory, meta = run_csrt(tmp_video, init_bbox_int)
            track_elapsed = time.time() - t0
            ok_count = sum(1 for t in trajectory if t["ok"])
            ok_rate = ok_count / len(trajectory)
            log(
                f"  csrt: {len(trajectory)} frames, ok={ok_rate:.1%}, "
                f"elapsed={track_elapsed:.2f}s"
            )

            # 마지막 프레임 viz (drift 시각 검증용) — 마지막 ok bbox 사용
            last_ok = next(
                (t for t in reversed(trajectory) if t["ok"] and t["bbox_xywh"]), None
            )
            if last_ok:
                last_frame = read_frame_at(tmp_video, last_ok["frame"])
                if last_frame is not None:
                    viz_last = draw_init_viz(
                        last_frame,
                        tuple(last_ok["bbox_xywh"]),
                        f"f{last_ok['frame']}",
                        ok_rate,
                    )
                    cv2.imwrite(str(TRAJ_DIR / f"{clip_id}_last.jpg"), viz_last)

            payload = {
                "clip_id": clip_id,
                "r2_key": r2_key,
                "detector": OWLV2_MODEL_ID,
                "init": {
                    "bbox_xywh": list(xywh),
                    "score": top["score"],
                    "label": top["label"],
                    "prompts": PROMPTS,
                    "area_ratio": area_ratio,
                },
                "video": {
                    "fps": meta["fps"],
                    "size": meta["size"],
                    "frame_count_meta": meta["frame_count_meta"],
                },
                "metrics": {
                    "ok_rate": ok_rate,
                    "detect_elapsed_sec": det_elapsed,
                    "track_elapsed_sec": track_elapsed,
                },
                "trajectory": trajectory,
            }
            (TRAJ_DIR / f"{clip_id}.json").write_text(json.dumps(payload, indent=2))

            result.update(
                {
                    "status": "ok",
                    "init_score": top["score"],
                    "init_area_ratio": area_ratio,
                    "ok_rate": ok_rate,
                    "frames": len(trajectory),
                    "detect_sec": det_elapsed,
                    "track_sec": track_elapsed,
                }
            )
            return result
        finally:
            tmp_video.unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001 — batch 안정성 우선, 개별 클립 에러 격리
        import traceback

        result["status"] = "error"
        result["error"] = f"{type(e).__name__}: {e}"
        if verbose:
            traceback.print_exc()
        return result


def write_batch_summary(results: list[dict]) -> Path:
    """results 를 csv 로 저장. Step 1.5 품질 게이트 평가의 입력."""
    import csv

    path = TRAJ_DIR / "batch-summary.csv"
    cols = [
        "clip_id",
        "status",
        "init_score",
        "init_area_ratio",
        "ok_rate",
        "frames",
        "detect_sec",
        "track_sec",
        "error",
    ]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow(r)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clip", help="단일 clip_id (없으면 게이트셋 첫 번째)")
    parser.add_argument(
        "--batch", action="store_true", help="게이트셋 전체 일괄 처리"
    )
    args = parser.parse_args()

    if args.batch:
        clip_ids = read_gate_clips()
        print(f"[batch] {len(clip_ids)} clips")
        results = []
        t_all = time.time()
        for i, cid in enumerate(clip_ids, 1):
            print(f"\n--- ({i}/{len(clip_ids)}) ---")
            r = process_clip(cid, verbose=True)
            results.append(r)
            done_ok = sum(1 for x in results if x.get("status") == "ok")
            elapsed = time.time() - t_all
            eta = elapsed / i * (len(clip_ids) - i)
            print(
                f"  → status={r['status']}, "
                f"done ok={done_ok}/{i}, "
                f"elapsed={elapsed/60:.1f}min, eta={eta/60:.1f}min"
            )
        summary_path = write_batch_summary(results)
        print(f"\n[summary] {summary_path}")
        print(
            "  status counts: "
            + ", ".join(
                f"{s}={sum(1 for r in results if r.get('status') == s)}"
                for s in ("ok", "no_detection", "no_valid_bbox", "error")
            )
        )
    else:
        cid = args.clip or first_clip_id()
        r = process_clip(cid, verbose=True)
        print(f"\nresult: {r}")


if __name__ == "__main__":
    main()
