"""SegmentVLM 샘플 artifact 생성기.

production 워커/DB 를 건드리지 않고, mismatch clip 1건을
`experiments/segment-vlm/sample-{clip8}/` 아래에 event mp4 + contact sheet +
metadata JSON 으로 떨군다.

사용 예:
    uv run python scripts/segmentvlm_sample_poc.py --clip-id d95e9eaa
    uv run python scripts/segmentvlm_sample_poc.py --limit 5

입력 후보는 `web/eval/v35/error-set-154.jsonl` 의 mismatch 목록이다.
`file_path` 가 없으면 notes 의 `auto-imported from inbox/...` 경로를 사용한다.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parent.parent
ERROR_SET = REPO_ROOT / "web" / "eval" / "v35" / "error-set-154.jsonl"
OUT_ROOT = REPO_ROOT / "experiments" / "segment-vlm"


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _iter_error_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in ERROR_SET.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _resolve_existing_path(path_text: str) -> Path | None:
    path = Path(path_text)
    if path.exists():
        return path

    # macOS 한글 파일명은 NFD/NFC 차이가 있어 path string 비교가 실패할 수 있다.
    parts = path.parts
    for i, part in enumerate(parts):
        if part == "inbox":
            base = Path(*parts[: i + 1])
            rest = parts[i + 1 :]
            cur = base
            for target in rest:
                if not cur.exists() or not cur.is_dir():
                    return None
                matched = None
                for child in cur.iterdir():
                    if _norm(child.name) == _norm(target):
                        matched = child
                        break
                if matched is None:
                    return None
                cur = matched
            return cur if cur.exists() else None
    return None


def _source_from_notes(notes: str | None) -> Path | None:
    if not notes:
        return None
    match = re.search(r"auto-imported from (inbox/.+)$", notes)
    if not match:
        return None
    return _resolve_existing_path(str(REPO_ROOT / match.group(1)))


def resolve_video(row: dict[str, Any]) -> Path | None:
    file_path = row.get("file_path")
    if isinstance(file_path, str):
        resolved = _resolve_existing_path(file_path)
        if resolved is not None:
            return resolved
    notes = row.get("notes")
    return _source_from_notes(notes if isinstance(notes, str) else None)


def _read_frame_at(video: Path, sec: float) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000)
    ok, frame = cap.read()
    cap.release()
    return frame if ok and frame is not None else None


def _fit_width(frame: np.ndarray, width: int = 360) -> np.ndarray:
    h, w = frame.shape[:2]
    return cv2.resize(frame, (width, int(width * h / w)))


def _label_img(img: np.ndarray, text: str) -> np.ndarray:
    out = img.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 34), (0, 0, 0), -1)
    cv2.putText(
        out,
        text,
        (8, 23),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return out


def segment_video(video: Path, *, sample_fps: float = 2.0) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if fps else 0.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    step = max(1, int(round(fps / sample_fps)))

    prev = None
    samples: list[dict[str, Any]] = []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            t = idx / fps
            small_h = int(320 * height / width) if width else frame.shape[0]
            small = cv2.resize(frame, (320, small_h)) if width else frame
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)
            if prev is None:
                ratio, cx, cy = 0.0, None, None
            else:
                delta = cv2.absdiff(prev, gray)
                _, mask = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)
                ratio = float(np.count_nonzero(mask) / mask.size * 100.0)
                ys, xs = np.nonzero(mask)
                if len(xs):
                    cx = float(xs.mean() / mask.shape[1])
                    cy = float(ys.mean() / mask.shape[0])
                else:
                    cx, cy = None, None
            prev = gray
            samples.append({"t": t, "changed_ratio": ratio, "cx": cx, "cy": cy})
        idx += 1
    cap.release()

    ratios = [s["changed_ratio"] for s in samples[1:]] or [0.0]
    p50 = float(np.percentile(ratios, 50))
    p75 = float(np.percentile(ratios, 75))
    p90 = float(np.percentile(ratios, 90))
    threshold = max(0.35, min(1.2, p75 + (p90 - p75) * 0.25))
    active = [s["changed_ratio"] >= threshold for s in samples]

    raw: list[dict[str, Any]] = []
    i = 0
    while i < len(samples):
        if not active[i]:
            i += 1
            continue
        start = samples[i]["t"]
        vals: list[float] = []
        cxs: list[float] = []
        cys: list[float] = []
        peak = samples[i]["changed_ratio"]
        while i < len(samples) and active[i]:
            vals.append(samples[i]["changed_ratio"])
            peak = max(peak, samples[i]["changed_ratio"])
            if samples[i]["cx"] is not None:
                cxs.append(samples[i]["cx"])
                cys.append(samples[i]["cy"])
            i += 1
        end = samples[min(i - 1, len(samples) - 1)]["t"] + 1 / sample_fps
        raw.append({"start": start, "end": end, "peak": peak, "vals": vals, "cxs": cxs, "cys": cys})

    pre, post, merge_gap, min_event, max_event = 3.0, 5.0, 4.0, 3.0, 20.0
    merged: list[dict[str, Any]] = []
    for r in raw:
        start = max(0.0, r["start"] - pre)
        end = min(duration, r["end"] + post)
        if merged and start - merged[-1]["end"] <= merge_gap:
            merged[-1]["end"] = max(merged[-1]["end"], end)
            merged[-1]["peak"] = max(merged[-1]["peak"], r["peak"])
            merged[-1]["vals"] += r["vals"]
            merged[-1]["cxs"] += r["cxs"]
            merged[-1]["cys"] += r["cys"]
        else:
            merged.append({"start": start, "end": end, "peak": r["peak"], "vals": list(r["vals"]), "cxs": list(r["cxs"]), "cys": list(r["cys"])})

    segments: list[dict[str, Any]] = []
    for m in merged:
        if m["end"] - m["start"] < min_event:
            continue
        if m["end"] - m["start"] <= max_event:
            segments.append(m)
        else:
            start = m["start"]
            while start < m["end"]:
                end = min(m["end"], start + max_event)
                segments.append({"start": start, "end": end, "peak": m["peak"], "vals": m["vals"], "cxs": m["cxs"], "cys": m["cys"]})
                start = end

    # 샘플 검수용: event가 너무 많으면 변화가 큰 상위 4개만.
    segments = sorted(segments, key=lambda x: (x["peak"], x["end"] - x["start"]), reverse=True)[:4]
    segments = sorted(segments, key=lambda x: x["start"])

    video_meta = {
        "fps": fps,
        "frame_count": frame_count,
        "duration_sec": round(duration, 2),
        "width": width,
        "height": height,
    }
    segmentation_meta = {
        "sample_fps": sample_fps,
        "threshold": round(float(threshold), 3),
        "ratio_p50": round(p50, 3),
        "ratio_p75": round(p75, 3),
        "ratio_p90": round(p90, 3),
    }
    return {"video": video_meta, "segmentation": segmentation_meta}, segments


def write_event_artifacts(video: Path, row: dict[str, Any], segments: list[dict[str, Any]], out_dir: Path) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    events: list[dict[str, Any]] = []

    for n, seg in enumerate(segments):
        start, end = float(seg["start"]), float(seg["end"])
        event_id = f"{row['clip_id']}:e{n:02d}"
        frame_count = 6 if end - start > 8 else 3
        times = np.linspace(start, end, frame_count)

        frames: list[np.ndarray] = []
        frame_paths: list[str] = []
        for t in times:
            frame = _read_frame_at(video, float(t))
            if frame is None:
                continue
            frame_path = frames_dir / f"event_{n:02d}_frame_{float(t):05.1f}s.jpg"
            cv2.imwrite(str(frame_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            frame_paths.append(str(frame_path.resolve()))
            frames.append(_label_img(_fit_width(frame), f"e{n} {float(t):05.1f}s"))

        contact_sheet = out_dir / f"event_{n:02d}_contact.jpg"
        if frames:
            cols = 3
            rows = math.ceil(len(frames) / cols)
            h, w = frames[0].shape[:2]
            canvas = np.full((rows * h, cols * w, 3), 245, np.uint8)
            for j, frame in enumerate(frames):
                y, x = (j // cols) * h, (j % cols) * w
                canvas[y : y + h, x : x + w] = frame
            cv2.imwrite(str(contact_sheet), canvas, [cv2.IMWRITE_JPEG_QUALITY, 88])

        event_mp4 = out_dir / f"event_{n:02d}.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{start:.3f}",
                "-to",
                f"{end:.3f}",
                "-i",
                str(video),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-an",
                str(event_mp4),
            ],
            check=False,
        )

        cxs, cys = seg.get("cxs") or [], seg.get("cys") or []
        events.append(
            {
                "event_id": event_id,
                "start_sec": round(start, 2),
                "end_sec": round(end, 2),
                "duration_sec": round(end - start, 2),
                "peak_changed_ratio": round(float(seg["peak"]), 3),
                "mean_changed_ratio": round(float(np.mean(seg.get("vals") or [0.0])), 3),
                "motion_centroid": [round(float(np.mean(cxs)), 3), round(float(np.mean(cys)), 3)] if cxs else None,
                "contact_sheet": str(contact_sheet.resolve()) if contact_sheet.exists() else None,
                "event_mp4": str(event_mp4.resolve()) if event_mp4.exists() else None,
                "key_frames": frame_paths,
            }
        )
    return events


def process_row(row: dict[str, Any]) -> Path | None:
    video = resolve_video(row)
    if video is None:
        return None
    clip_id = row["clip_id"]
    out_dir = OUT_ROOT / f"sample-{clip_id[:8]}"
    meta_parts, segments = segment_video(video)
    events = write_event_artifacts(video, row, segments, out_dir)
    payload = {
        "clip_id": clip_id,
        "source_video": str(video.resolve()),
        "gt_action": row.get("gt"),
        "baseline_action": row.get("raw"),
        "baseline_error": f"GT {row.get('gt')}, Gemini v3.5 predicted {row.get('raw')}",
        "notes": row.get("notes"),
        **meta_parts,
        "events": events,
    }
    (out_dir / "segmentvlm_sample.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clip-id", help="clip_id prefix or full uuid")
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args()

    rows = _iter_error_rows()
    if args.clip_id:
        rows = [r for r in rows if r["clip_id"].startswith(args.clip_id)]
    made = 0
    for row in rows:
        out = process_row(row)
        if out is None:
            print(f"MISS {row['clip_id'][:8]} video not found")
            continue
        print(f"OK {row['clip_id'][:8]} -> {out}")
        made += 1
        if made >= args.limit:
            break
    if made == 0:
        raise SystemExit("no samples generated")


if __name__ == "__main__":
    main()
