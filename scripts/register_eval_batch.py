"""eval 배치 등록 (범용) — R2 업로드 + camera_clips + behavior_logs + manifest 행 추가.

register_eval0608/0615/0617 의 공통 로직을 인자 받는 단일 스크립트로 통합.
입력 폴더의 영상을 `clips/eval-{eval_id}/` 로 올리고 production DB + 평가 manifest 에 등록.

규칙 (eval-0615/0617 패턴 표준):
- 입력 파일명 prefix 로 GT 판정 (`gt_from_name`): drinking/eating-paste/eating-prey/hand-feeding/not-drinking.
- R2/manifest 네이밍 = `{gt}__na__{clip8}.mp4` (clip8 = clip_id 앞 8자). manifest filename 과 r2_key 일치 → grep/조회 일관.
- manifest.csv(storage/dataset-203/) 행까지 추가 — 평가 SOT 가 manifest, DB 는 production SOT. 둘 다 채운다.
- 회귀셋 동결 유지: source=eval-{id} 로 전체 평가셋에만 포함, 버전 paired 회귀(185)엔 미포함.
- quality_tag 빈칸 — 사용자 육안 직접 태깅(self-bias 방지).
- 멱등: camera_clips.file_path 에 원본 파일명 있으면 skip (재실행 안전).

실행:
  PYTHONPATH=. uv run python scripts/register_eval_batch.py --eval-id 0618 --inbox ~/Downloads/new-data-2026-06-18           # dry-run
  PYTHONPATH=. uv run python scripts/register_eval_batch.py --eval-id 0618 --inbox ~/Downloads/new-data-2026-06-18 --apply   # 실제 업로드+INSERT+manifest
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.r2_uploader import get_r2_bucket, get_r2_client  # noqa: E402

MANIFEST = REPO / "storage" / "dataset-203" / "manifest.csv"
OWNER_USER_ID = "380d97fd-cb83-4490-ac26-cf691b32614f"  # owner (eval-0608/0617 동일)
CRESTED_PET_ID = "55518f35-b251-4ed7-962f-b65611d63223"  # owner crested-gecko pet

MANIFEST_COLS = [
    "filename", "clip_id", "gt", "pred_v36", "pred_v361", "match",
    "species", "source", "r2_key", "quality_tag", "tag_basis",
]


def gt_from_name(name: str) -> str:
    """파일명 prefix → GT action. not-drinking 을 drinking 보다 먼저 (substring 충돌)."""
    n = name.lower()
    if n.startswith("not-drinking"):
        return "moving"
    if n.startswith("hand-feeding"):
        return "hand_feeding"
    if n.startswith("eating-paste"):
        return "eating_paste"
    if n.startswith("eating-prey"):
        return "eating_prey"
    if n.startswith("drinking"):
        return "drinking"
    raise ValueError(f"GT 매핑 실패 (예상 못 한 파일명): {name}")


def probe(path: Path) -> dict:
    """ffprobe 로 width/height/fps/codec/duration 추출."""
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate,codec_name:format=duration",
            "-of", "json", str(path),
        ]
    ).decode()
    d = json.loads(out)
    st = d["streams"][0]
    fmt = d.get("format", {})
    fr = st.get("avg_frame_rate", "0/1")
    num, den = (fr.split("/") + ["1"])[:2]
    fps = round(float(num) / float(den), 2) if float(den) else None
    dur = fmt.get("duration")
    return {
        "width": st.get("width"),
        "height": st.get("height"),
        "fps": fps,
        "codec": st.get("codec_name"),
        "duration_sec": round(float(dur), 3) if dur else None,
    }


def content_type(name: str) -> str:
    return "video/mp4" if name.lower().endswith(".mp4") else "video/quicktime"


def existing_src_names(sb, inbox: Path) -> set[str]:
    """이미 등록된 원본 파일명 (camera_clips.file_path 기반 멱등)."""
    rows = (
        sb.table("camera_clips")
        .select("file_path")
        .like("file_path", f"%{inbox.name}%")
        .execute()
        .data
    )
    return {Path(r["file_path"]).name for r in rows if r.get("file_path")}


def manifest_append(row: dict) -> None:
    with open(MANIFEST, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=MANIFEST_COLS).writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser(description="eval 배치 등록 (R2 + DB + manifest)")
    ap.add_argument("--eval-id", required=True,
                    help="예: 0618 → clips/eval-0618/, source=eval-0618")
    ap.add_argument("--inbox", required=True, type=Path,
                    help="등록할 영상 폴더 (예: ~/Downloads/new-data-2026-06-18)")
    ap.add_argument("--apply", action="store_true",
                    help="실제 업로드+INSERT+manifest (없으면 dry-run 출력만)")
    args = ap.parse_args()

    inbox = args.inbox.expanduser()
    if not inbox.is_dir():
        sys.exit(f"입력 폴더 없음: {inbox}")
    r2_prefix = f"clips/eval-{args.eval_id}"
    source = f"eval-{args.eval_id}"
    apply = args.apply

    load_dotenv(REPO / ".env")
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    videos = sorted(
        p for p in inbox.iterdir()
        if p.suffix.lower() in {".mov", ".mp4"} and not p.name.startswith(".")
    )
    print(f"{inbox.name} 영상 {len(videos)}개 → {r2_prefix}/, mode={'APPLY' if apply else 'DRY-RUN'}")

    already = existing_src_names(sb, inbox)
    print(f"이미 등록된 원본: {len(already)}개\n")

    client = get_r2_client() if apply else None
    bucket = get_r2_bucket() if apply else "(dry-run)"

    gt_counter: dict[str, int] = {}
    done = skipped = 0

    for p in videos:
        gt = gt_from_name(p.name)  # 매핑 실패 시 raise — 예상 못 한 파일명 즉시 중단

        if p.name in already:
            print(f"  [skip] {p.name}  (이미 등록됨)")
            skipped += 1
            continue

        gt_counter[gt] = gt_counter.get(gt, 0) + 1
        meta = probe(p)
        size = p.stat().st_size
        clip_id = str(uuid.uuid4())
        clip8 = clip_id[:8]
        filename = f"{gt}__na__{clip8}.mp4"
        r2_key = f"{r2_prefix}/{filename}"
        started = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()

        clip_row = {
            "id": clip_id,
            "user_id": OWNER_USER_ID,
            "pet_id": CRESTED_PET_ID,
            "source": "upload",
            "started_at": started,
            "duration_sec": meta["duration_sec"],
            "has_motion": True,
            "width": meta["width"],
            "height": meta["height"],
            "fps": meta["fps"],
            "codec": meta["codec"],
            "file_size": size,
            "original_file_size": size,
            "encoded_file_size": size,
            "file_path": str(p),
            "r2_key": r2_key,
        }
        log_row = {
            "clip_id": clip_id,
            "frame_idx": 0,
            "action": gt,
            "source": "human",
            "verified": True,
            "notes": f"{source} GT (파일명 힌트, src={p.name})",
            "created_by": OWNER_USER_ID,
        }
        manifest_row = {
            "filename": filename,
            "clip_id": clip_id,
            "gt": gt,
            "pred_v36": "na",
            "pred_v361": "na",
            "match": "na",
            "species": "crested-gecko",
            "source": source,
            "r2_key": r2_key,
            "quality_tag": "",
            "tag_basis": "none",
        }

        print(f"  {p.name}")
        print(
            f"     GT={gt}  {filename}  "
            f"{meta['width']}x{meta['height']} {meta['fps']}fps {meta['duration_sec']}s {size / 1e6:.1f}MB"
        )

        if not apply:
            done += 1
            continue

        # 1. R2 업로드 (멀티파트 자동 — 4K 100MB+ 대비)
        client.upload_file(
            str(p), bucket, r2_key, ExtraArgs={"ContentType": content_type(p.name)}
        )
        # 2. camera_clips INSERT
        sb.table("camera_clips").insert(clip_row).execute()
        # 3. behavior_logs GT INSERT
        sb.table("behavior_logs").insert(log_row).execute()
        # 4. 로컬 평가용 복사 — _extract_frames_clip 이 storage/dataset-203/{filename} 를 읽음
        shutil.copy2(p, MANIFEST.parent / filename)
        # 5. manifest 행 추가 (평가 SOT)
        manifest_append(manifest_row)
        print("     -> uploaded + inserted + copied + manifest ✅")
        done += 1

    print(f"\n{'=' * 56}")
    print(f"GT 분포: {gt_counter}  (합 {sum(gt_counter.values())})")
    print(f"처리 {done}, skip {skipped}, mode={'APPLY' if apply else 'DRY-RUN'}")
    if not apply:
        print(f"\n검수 후 실제 실행: --apply 추가")
    else:
        n = sum(1 for _ in open(MANIFEST)) - 1
        print(f"manifest 총 {n}행")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
