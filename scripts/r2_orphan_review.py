#!/usr/bin/env python3
"""R2 orphan clip manual-review pack generator.

`r2_orphan_inventory.py` 가 만든 `orphans.jsonl` 을 입력으로 받아, 사람이
판단하기 쉬운 로컬 리뷰팩을 만든다. DB/R2 쓰기는 하지 않는다.

사용:
    uv run python scripts/r2_orphan_review.py \
      --orphans reports/r2-orphan-inventory-20260710/orphans.jsonl \
      --out-dir reports/r2-orphan-review-20260710
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.r2_uploader import get_r2_bucket, get_r2_client  # noqa: E402
from backend.supabase_client import get_supabase_client  # noqa: E402

DEFAULT_ORPHANS = REPO_ROOT / "reports/r2-orphan-inventory-20260710/orphans.jsonl"
DEFAULT_OUT_DIR = REPO_ROOT / "reports/r2-orphan-review-20260710"
CSV_FIELDS = [
    "r2_key",
    "classification",
    "import_confidence",
    "camera_hint",
    "clip_id",
    "date",
    "last_modified",
    "size",
    "local_clip_path",
    "thumbnail_path",
    "visual_status",
    "duration_sec",
    "width",
    "height",
    "fps",
    "frame_count",
    "motion_score",
    "db_match",
    "decision",
    "notes",
]


@dataclass(frozen=True, slots=True)
class VideoEvidence:
    local_clip_path: str
    thumbnail_path: str | None
    openable: bool
    duration_sec: float | None
    width: int | None
    height: int | None
    fps: float | None
    frame_count: int | None
    motion_score: float | None


def load_orphan_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def build_review_row(
    orphan: dict[str, Any],
    *,
    evidence: VideoEvidence,
    db_match_count: int,
) -> dict[str, Any]:
    db_match = "possible_duplicate" if db_match_count else "no_match"
    visual_status = "openable" if evidence.openable else "broken_or_unreadable"
    if not evidence.openable:
        decision = "ignore"
        notes = "video cannot be opened by OpenCV"
    elif db_match_count:
        decision = "ignore"
        notes = f"{db_match_count} existing camera_clips near timestamp"
    else:
        decision = "needs_human_label"
        notes = "legacy path; camera/user mapping uncertain"

    return {
        "r2_key": orphan.get("key"),
        "classification": orphan.get("classification"),
        "import_confidence": orphan.get("import_confidence"),
        "camera_hint": orphan.get("camera_id"),
        "clip_id": orphan.get("clip_id"),
        "date": orphan.get("date"),
        "last_modified": orphan.get("last_modified"),
        "size": orphan.get("size"),
        "local_clip_path": evidence.local_clip_path,
        "thumbnail_path": evidence.thumbnail_path,
        "visual_status": visual_status,
        "duration_sec": evidence.duration_sec,
        "width": evidence.width,
        "height": evidence.height,
        "fps": evidence.fps,
        "frame_count": evidence.frame_count,
        "motion_score": evidence.motion_score,
        "db_match": db_match,
        "decision": decision,
        "notes": notes,
    }


def write_review_pack(review_rows: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "review.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(review_rows)

    (out_dir / "review.json").write_text(
        json.dumps(review_rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "REVIEW.md").write_text(
        _format_review_markdown(review_rows, out_dir),
        encoding="utf-8",
    )


def download_r2_clip(r2_key: str, out_dir: Path) -> Path:
    clips_dir = out_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    dst = clips_dir / _safe_clip_filename(r2_key)
    get_r2_client().download_file(get_r2_bucket(), r2_key, str(dst))
    return dst


def extract_video_evidence(video_path: Path, out_dir: Path) -> VideoEvidence:
    thumb_dir = out_dir / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            return VideoEvidence(
                local_clip_path=str(video_path),
                thumbnail_path=None,
                openable=False,
                duration_sec=None,
                width=None,
                height=None,
                fps=None,
                frame_count=None,
                motion_score=None,
            )

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = round(frame_count / fps, 2) if fps > 0 and frame_count else None

        ok, first_frame = cap.read()
        thumbnail_path = None
        motion_score = None
        if ok:
            thumbnail = thumb_dir / f"{video_path.stem}.jpg"
            cv2.imwrite(str(thumbnail), first_frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
            thumbnail_path = str(thumbnail)
            motion_score = _estimate_motion_score(cap, first_frame, frame_count)

        return VideoEvidence(
            local_clip_path=str(video_path),
            thumbnail_path=thumbnail_path,
            openable=True,
            duration_sec=duration,
            width=width or None,
            height=height or None,
            fps=round(fps, 2) if fps else None,
            frame_count=frame_count or None,
            motion_score=motion_score,
        )
    finally:
        cap.release()


def count_possible_db_matches(orphan: dict[str, Any], window_minutes: int = 10) -> int:
    last_modified = orphan.get("last_modified")
    if not isinstance(last_modified, str) or not last_modified:
        return 0
    try:
        center = datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
    except ValueError:
        return 0
    start = (center - timedelta(minutes=window_minutes)).astimezone(timezone.utc)
    end = (center + timedelta(minutes=window_minutes)).astimezone(timezone.utc)
    resp = (
        get_supabase_client()
        .table("camera_clips")
        .select("id,started_at,r2_key")
        .gte("started_at", start.isoformat())
        .lte("started_at", end.isoformat())
        .limit(20)
        .execute()
    )
    return len(resp.data or [])


def build_review_pack(
    orphans_path: Path,
    out_dir: Path,
    *,
    skip_download: bool = False,
) -> list[dict[str, Any]]:
    rows = load_orphan_rows(orphans_path)
    review_rows: list[dict[str, Any]] = []
    for orphan in rows:
        r2_key = orphan["key"]
        if skip_download:
            local_path = out_dir / "clips" / _safe_clip_filename(r2_key)
            evidence = VideoEvidence(
                local_clip_path=str(local_path),
                thumbnail_path=None,
                openable=False,
                duration_sec=None,
                width=None,
                height=None,
                fps=None,
                frame_count=None,
                motion_score=None,
            )
        else:
            local_path = download_r2_clip(r2_key, out_dir)
            evidence = extract_video_evidence(local_path, out_dir)
        review_rows.append(
            build_review_row(
                orphan,
                evidence=evidence,
                db_match_count=count_possible_db_matches(orphan),
            )
        )
    write_review_pack(review_rows, out_dir)
    return review_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orphans", type=Path, default=DEFAULT_ORPHANS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="only create placeholder review rows; no R2 reads",
    )
    args = parser.parse_args()

    review_rows = build_review_pack(
        args.orphans,
        args.out_dir,
        skip_download=args.skip_download,
    )
    decisions = Counter(row["decision"] for row in review_rows)
    print(f"review rows: {len(review_rows)}")
    print(f"decisions: {dict(decisions)}")
    print(f"reports: {args.out_dir}")
    print("DB writes: 0 / R2 writes: 0")
    return 0


def _estimate_motion_score(
    cap: cv2.VideoCapture,
    first_frame: Any,
    frame_count: int,
    sample_count: int = 6,
) -> float | None:
    if frame_count <= 1:
        return None
    prev = cv2.cvtColor(first_frame, cv2.COLOR_BGR2GRAY)
    scores: list[float] = []
    step = max(frame_count // sample_count, 1)
    for idx in range(step, frame_count, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(prev, gray)
        scores.append(float(diff.mean() / 255.0))
        prev = gray
        if len(scores) >= sample_count:
            break
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


def _format_review_markdown(review_rows: list[dict[str, Any]], out_dir: Path) -> str:
    decisions = Counter(row["decision"] for row in review_rows)
    visual = Counter(row["visual_status"] for row in review_rows)
    lines = [
        "# R2 Orphan Manual Review Pack",
        "",
        f"- generated_at: `{datetime.now(timezone.utc).isoformat()}`",
        f"- total_rows: `{len(review_rows)}`",
        "- DB writes: `0`",
        "- R2 writes: `0`",
        "- R2 reads/downloads: local review copy only",
        "",
        "## Decisions",
        "",
    ]
    for key in sorted(decisions):
        lines.append(f"- `{key}`: {decisions[key]}")
    lines.extend(["", "## Visual Status", ""])
    for key in sorted(visual):
        lines.append(f"- `{key}`: {visual[key]}")
    lines.extend(
        [
            "",
            "## Files",
            "",
            f"- `{out_dir / 'review.csv'}`",
            f"- `{out_dir / 'review.json'}`",
            f"- `{out_dir / 'clips'}`",
            f"- `{out_dir / 'thumbnails'}`",
            "",
        ]
    )
    return "\n".join(lines)


def _safe_clip_filename(r2_key: str) -> str:
    stem = Path(r2_key).stem
    return f"{stem}.mp4"


if __name__ == "__main__":
    raise SystemExit(main())
