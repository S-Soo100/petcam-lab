"""44개 VLM mismatch 영상을 GT·예측 없이 검토하기 위한 순수 보조 도구."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path

import cv2
import numpy as np


CAUSES = {
    "VISIBILITY_SCALE_OCCLUSION",
    "TEMPORAL_SAMPLING",
    "IR_LIGHT_REFLECTION",
    "CAMERA_DOMAIN",
    "SEMANTIC_ONTOLOGY",
    "INPUT_QUALITY",
    "GT_AMBIGUITY_OR_ERROR",
    "PIPELINE_PROVENANCE",
    "OTHER_UNRESOLVED",
}
JUDGEABILITY = {"judgeable", "unjudgeable"}


def uniform_frame_indices(frame_count: int, samples: int) -> list[int]:
    if frame_count <= 0 or samples <= 0:
        return []
    sample_count = min(frame_count, samples)
    if sample_count == 1:
        return [0]
    return [
        round(index * (frame_count - 1) / (sample_count - 1))
        for index in range(sample_count)
    ]


def compose_contact_sheet(
    frames: list[np.ndarray],
    *,
    columns: int,
) -> np.ndarray:
    if not frames:
        raise ValueError("empty_frames")
    if columns <= 0:
        raise ValueError("invalid_columns")
    height, width = frames[0].shape[:2]
    if any(frame.shape[:2] != (height, width) for frame in frames):
        raise ValueError("inconsistent_frame_shapes")
    rows = math.ceil(len(frames) / columns)
    sheet = np.zeros((rows * height, columns * width, 3), dtype=np.uint8)
    for index, frame in enumerate(frames):
        row, column = divmod(index, columns)
        sheet[
            row * height : (row + 1) * height,
            column * width : (column + 1) * width,
        ] = frame
    return sheet


def validate_review_row(row: dict) -> None:
    review_id = row.get("review_id")
    if not isinstance(review_id, str) or not review_id.startswith("review-"):
        raise ValueError("invalid_review_id")
    judgeability = row.get("judgeability")
    if judgeability not in JUDGEABILITY:
        raise ValueError("invalid_judgeability")
    primary = row.get("primary_cause")
    secondary = row.get("secondary_causes")
    if not isinstance(secondary, list) or len(secondary) > 2:
        raise ValueError("invalid_secondary_causes")
    if judgeability == "unjudgeable":
        if primary is not None or secondary:
            raise ValueError("unjudgeable_with_cause")
        return
    if primary not in CAUSES:
        raise ValueError("unknown_primary_cause")
    if any(cause not in CAUSES for cause in secondary):
        raise ValueError("unknown_secondary_cause")
    if primary in secondary or len(set(secondary)) != len(secondary):
        raise ValueError("duplicate_cause")


def summarize_reviews(rows: list[dict]) -> dict:
    for row in rows:
        validate_review_row(row)
    return {
        "rows": len(rows),
        "judgeability": dict(
            sorted(Counter(row["judgeability"] for row in rows).items())
        ),
        "primary_causes": dict(
            sorted(
                Counter(
                    row["primary_cause"]
                    for row in rows
                    if row["primary_cause"] is not None
                ).items()
            )
        ),
        "secondary_causes": dict(
            sorted(
                Counter(
                    cause
                    for row in rows
                    for cause in row["secondary_causes"]
                ).items()
            )
        ),
    }


def render_contact_sheet(
    video_path: Path,
    output_path: Path,
    *,
    samples: int = 12,
    columns: int = 4,
    frame_width: int = 480,
) -> None:
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise ValueError(f"video_not_openable {video_path.name}")
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        frames: list[np.ndarray] = []
        for frame_index in uniform_frame_indices(frame_count, samples):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = cap.read()
            if not ok:
                raise ValueError(
                    f"frame_read_failed {video_path.name} {frame_index}"
                )
            scale = frame_width / frame.shape[1]
            resized = cv2.resize(
                frame,
                (frame_width, max(1, round(frame.shape[0] * scale))),
                interpolation=cv2.INTER_AREA,
            )
            timestamp = frame_index / fps if fps > 0 else 0
            cv2.putText(
                resized,
                f"{timestamp:05.1f}s",
                (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )
            frames.append(resized)
        sheet = compose_contact_sheet(frames, columns=columns)
        cv2.putText(
            sheet,
            video_path.stem,
            (10, sheet.shape[0] - 12),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(
            str(output_path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 92]
        ):
            raise ValueError(f"sheet_write_failed {output_path.name}")
    finally:
        cap.release()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-dir", type=Path)
    parser.add_argument("--sheet-dir", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--summary-out", type=Path)
    args = parser.parse_args()
    if args.video_dir and args.sheet_dir:
        videos = sorted(args.video_dir.glob("review-*.mp4"))
        for video_path in videos:
            render_contact_sheet(
                video_path, args.sheet_dir / f"{video_path.stem}.jpg"
            )
        print(f"BLIND_SHEETS_OK {len(videos)}")
        return 0
    if args.reviews and args.summary_out:
        rows = json.loads(args.reviews.read_text(encoding="utf-8"))
        summary = summarize_reviews(rows)
        args.summary_out.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("BLIND_REVIEW_SUMMARY_OK")
        return 0
    parser.error(
        "use --video-dir/--sheet-dir or --reviews/--summary-out"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
