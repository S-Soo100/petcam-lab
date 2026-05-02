"""
camera_clips 의 r2_key NULL row 를 인코딩 + R2 업로드 + DB UPDATE.

spec §4 결정 2 의 후속 batch backfill 스크립트 (이번 스펙 Out 으로 분류됐던 것).
백엔드 EncodeUploadWorker 와 동일한 인코딩/업로드 로직을 sync 로 풀어 단발 실행.

## 흐름
1. 대상 SELECT — `r2_key IS NULL` (기본: `has_motion=true` 추가 필터)
2. 각 row sequential 처리:
   a. file_path 존재 확인 (없으면 skip)
   b. encoded_dst 빌드 (`storage/encoded/{date}/{cam}/{stem}_{id}.mp4`)
   c. encode_lightweight (CRF 26)
   d. R2 업로드 (mp4 + thumbnail) — 키 패턴은 EncodeUploadWorker 와 동일
   e. DB UPDATE r2_key, thumbnail_r2_key, encoded_file_size, original_file_size

## 사용 예
    # dry-run — 대상 카운트만
    uv run python scripts/backfill_motion_r2.py --dry-run

    # 5 건만
    uv run python scripts/backfill_motion_r2.py --limit 5

    # motion 전체 (376건)
    uv run python scripts/backfill_motion_r2.py

    # idle 까지 모두
    uv run python scripts/backfill_motion_r2.py --all-null

## 안전성
- 백엔드(EncodeUploadWorker) 와 병행 가능 — R2 키에 row id 박혀 충돌 없음.
- DB UPDATE 는 r2_key 채운 row 만 → 재실행 idempotent.
- 인코딩 결과는 storage/encoded/ 보존 (캐시 / 재실행 시 재인코딩 회피는 별개 옵션).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.encoding import FFmpegNotFound, encode_lightweight  # noqa: E402
from backend.r2_uploader import (  # noqa: E402
    BotoCoreError,
    ClientError,
    R2NotConfigured,
    upload_clip,
)
from backend.supabase_client import get_supabase_client  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("backfill")

# 백엔드 서버에 의존하지 않게 따로 잡힘. 같은 저장 루트.
ENCODED_DIR = REPO_ROOT / "storage" / "encoded"


def _date_str_for_clip(file_path: Path, started_at: str) -> str:
    """R2 키의 날짜 부분. capture 워커가 storage/clips/<date>/<cam>/* 로 쓰니
    parent.parent.name 우선, 깨졌으면 started_at ISO 앞 10자."""
    candidate = file_path.parent.parent.name
    if _is_iso_date(candidate):
        return candidate
    return started_at[:10] if _is_iso_date(started_at[:10]) else "unknown-date"


def _is_iso_date(s: str) -> bool:
    if not isinstance(s, str) or len(s) != 10:
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _process_row(row: dict, dry_run: bool) -> tuple[bool, str]:
    """1건 처리. (성공 여부, reason) 리턴."""
    clip_id = row["id"]
    # camera_id NULL = PoC 사용자 업로드 (source='upload'). R2 키에 "uploaded" literal —
    # 카메라 캡처와 attribution 분리해 식별 가능. spec §3-4 NULL 88건 결정 (b) (2026-05-02).
    camera_seg = row["camera_id"] or "uploaded"
    file_path_raw = row.get("file_path")
    if not file_path_raw:
        return False, "no file_path"

    src = Path(file_path_raw)
    if not src.is_file():
        return False, f"missing on disk ({src})"

    thumb_raw = row.get("thumbnail_path")
    thumb = Path(thumb_raw) if thumb_raw else None
    thumb_alive = bool(thumb and thumb.is_file())

    started_at = row.get("started_at") or ""
    date_str = _date_str_for_clip(src, started_at)
    stem = src.stem

    mp4_key = f"clips/{camera_seg}/{date_str}/{stem}_{clip_id}.mp4"
    thumb_key = (
        f"thumbnails/{camera_seg}/{date_str}/{stem}_{clip_id}.jpg"
        if thumb_alive
        else None
    )
    encoded_dst = ENCODED_DIR / date_str / camera_seg / f"{stem}_{clip_id}.mp4"

    if dry_run:
        logger.info(
            "[dry-run] %s -> %s (thumb=%s)",
            src.name,
            mp4_key,
            "yes" if thumb_alive else "no",
        )
        return True, "dry-run"

    try:
        encoded_dst.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"mkdir failed: {exc}"

    try:
        encode_ok = encode_lightweight(src, encoded_dst)
    except (FileNotFoundError, ValueError, FFmpegNotFound) as exc:
        return False, f"encode pre-check: {exc}"

    if not encode_ok:
        return False, "encode failed"

    try:
        encoded_size = encoded_dst.stat().st_size
    except OSError:
        return False, "encoded stat failed"

    try:
        upload_clip(encoded_dst, mp4_key, "video/mp4")
    except (R2NotConfigured, ClientError, BotoCoreError, OSError) as exc:
        return False, f"r2 mp4 upload: {exc}"

    thumb_uploaded = False
    if thumb_alive and thumb_key is not None and thumb is not None:
        try:
            upload_clip(thumb, thumb_key, "image/jpeg")
            thumb_uploaded = True
        except (R2NotConfigured, ClientError, BotoCoreError, OSError) as exc:
            logger.warning("thumb upload skipped (key=%s): %s", thumb_key, exc)

    update_payload = {
        "r2_key": mp4_key,
        "thumbnail_r2_key": thumb_key if thumb_uploaded else None,
        "encoded_file_size": encoded_size,
        "original_file_size": row.get("file_size"),
    }
    sb = get_supabase_client()
    sb.table("camera_clips").update(update_payload).eq("id", clip_id).execute()

    return True, f"ok ({encoded_size:,}B / orig {row.get('file_size'):,}B)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="처리 최대 건수")
    ap.add_argument("--dry-run", action="store_true", help="DB/R2 변경 없이 대상만 출력")
    ap.add_argument(
        "--all-null",
        action="store_true",
        help="has_motion 무관 r2_key NULL 모두 (기본은 motion 만)",
    )
    args = ap.parse_args()

    sb = get_supabase_client()
    # camera_id NULL 도 처리 (PoC 사용자 업로드는 R2 키에 "uploaded" literal — _process_row 참조)
    q = sb.table("camera_clips").select(
        "id,camera_id,started_at,file_path,thumbnail_path,file_size,has_motion"
    ).is_("r2_key", "null")
    if not args.all_null:
        q = q.eq("has_motion", True)
    q = q.order("started_at", desc=False)
    if args.limit:
        q = q.limit(args.limit)
    rows = q.execute().data
    logger.info(
        "target rows: %d (filter: %s, limit: %s, dry_run: %s)",
        len(rows),
        "r2_key NULL" if args.all_null else "motion=true AND r2_key NULL",
        args.limit,
        args.dry_run,
    )
    if not rows:
        return 0

    succ, skip, fail = 0, 0, 0
    failures: list[tuple[str, str]] = []
    started = time.time()

    for i, row in enumerate(rows, 1):
        try:
            ok, reason = _process_row(row, args.dry_run)
        except Exception as exc:  # noqa: BLE001
            logger.exception("unexpected error on %s", row["id"])
            ok, reason = False, f"unexpected: {type(exc).__name__}: {exc}"

        if ok:
            succ += 1
        else:
            if "missing on disk" in reason or "no file_path" in reason:
                skip += 1
            else:
                fail += 1
                failures.append((row["id"], reason))

        if i % 10 == 0 or i == len(rows):
            elapsed = time.time() - started
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(rows) - i) / rate if rate > 0 else 0
            logger.info(
                "[%d/%d] succ=%d skip=%d fail=%d  rate=%.1f/s  eta=%.0fs",
                i,
                len(rows),
                succ,
                skip,
                fail,
                rate,
                eta,
            )

    elapsed = time.time() - started
    logger.info(
        "DONE total=%d succ=%d skip=%d fail=%d  elapsed=%.1fs",
        len(rows),
        succ,
        skip,
        fail,
        elapsed,
    )
    if failures:
        logger.warning("failures (%d):", len(failures))
        for cid, reason in failures[:20]:
            logger.warning("  %s — %s", cid, reason)
        if len(failures) > 20:
            logger.warning("  ... +%d more", len(failures) - 20)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
