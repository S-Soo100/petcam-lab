"""eval-0608 신규 evidence셋 등록 — R2 업로드 + camera_clips + behavior_logs GT INSERT.

inbox/0608 의 44개 로컬 영상을 `clips/eval-0608/` 로 올리고 production DB 에 등록한다.
159 동결셋과는 분리: `load_eval_set` 은 화이트리스트라 안 섞이고, 신규 44건은
`load_eval_set_0608` (prefix 필터)로 따로 로드한다.

- 종: 전부 crested_gecko (owner pet). camera_clips.pet_id 로 연결.
- GT: 파일명 힌트 → action. not-drinking-just-licking-own-face → moving
  (drinking false-positive hard negative).
- multipart: 4K 100MB+ 파일이 있어 boto3 `upload_file`(자동 멀티파트) 사용
  — r2_uploader.upload_clip 의 put_object(단일) 는 큰 파일에 부적합.
- 멱등: r2_key 가 이미 camera_clips 에 있으면 skip (재실행 안전).

실행:
  PYTHONPATH=. uv run python scripts/register_eval0608.py            # dry-run (출력만)
  PYTHONPATH=. uv run python scripts/register_eval0608.py --apply    # 실제 업로드+INSERT
"""

from __future__ import annotations

import json
import os
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

INBOX = REPO / "inbox" / "0608"
R2_PREFIX = "clips/eval-0608"
OWNER_USER_ID = "380d97fd-cb83-4490-ac26-cf691b32614f"  # probe 확인 — camera_clips 전부 이 user
CRESTED_PET_ID = "55518f35-b251-4ed7-962f-b65611d63223"  # owner crested-gecko pet (probe)

APPLY = "--apply" in sys.argv

load_dotenv(REPO / ".env")
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


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


def existing_r2_keys() -> set[str]:
    """이미 등록된 eval-0608 r2_key (멱등성)."""
    rows = (
        sb.table("camera_clips")
        .select("r2_key")
        .like("r2_key", f"{R2_PREFIX}/%")
        .execute()
        .data
    )
    return {r["r2_key"] for r in rows if r.get("r2_key")}


def main() -> int:
    videos = sorted(
        p for p in INBOX.iterdir()
        if p.suffix.lower() in {".mov", ".mp4"} and not p.name.startswith(".")
    )
    print(f"inbox/0608 영상 {len(videos)}개, mode={'APPLY' if APPLY else 'DRY-RUN'}")

    # dry-run: 기존 behavior_logs human 샘플 1개로 컬럼 패턴 확인
    if not APPLY:
        sample = (
            sb.table("behavior_logs").select("*").eq("source", "human").limit(1).execute().data
        )
        print("\n[참고] 기존 behavior_logs(source=human) 샘플 컬럼:")
        if sample:
            for k, v in sample[0].items():
                print(f"    {k:14s} = {json.dumps(v, ensure_ascii=False)[:50]}")

    already = existing_r2_keys()
    print(f"\n이미 등록된 eval-0608 r2_key: {len(already)}개\n")

    client = get_r2_client() if APPLY else None
    bucket = get_r2_bucket() if APPLY else "(dry-run)"

    gt_counter: dict[str, int] = {}
    done = skipped = 0

    for p in videos:
        gt = gt_from_name(p.name)
        gt_counter[gt] = gt_counter.get(gt, 0) + 1
        r2_key = f"{R2_PREFIX}/{p.name}"

        if r2_key in already:
            print(f"  [skip] {p.name}  (이미 등록됨)")
            skipped += 1
            continue

        meta = probe(p)
        size = p.stat().st_size
        clip_id = str(uuid.uuid4())
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
        note = "eval-0608 GT (파일명 힌트)"
        if gt == "moving":
            note += " — drinking false-positive hard negative"
        log_row = {
            "clip_id": clip_id,
            "frame_idx": 0,
            "action": gt,
            "source": "human",
            "verified": True,
            "notes": note,
            "created_by": OWNER_USER_ID,
        }

        print(f"  {p.name}")
        print(f"     GT={gt}  {meta['width']}x{meta['height']} {meta['fps']}fps {meta['duration_sec']}s {size/1e6:.1f}MB")

        if not APPLY:
            done += 1
            continue

        # 1. R2 업로드 (멀티파트 자동)
        client.upload_file(
            str(p), bucket, r2_key,
            ExtraArgs={"ContentType": content_type(p.name)},
        )
        # 2. camera_clips INSERT
        sb.table("camera_clips").insert(clip_row).execute()
        # 3. behavior_logs GT INSERT
        sb.table("behavior_logs").insert(log_row).execute()
        print("     -> uploaded + inserted ✅")
        done += 1

    print(f"\n{'=' * 56}")
    print(f"GT 분포: {gt_counter}  (합 {sum(gt_counter.values())})")
    print(f"처리 {done}, skip {skipped}, mode={'APPLY' if APPLY else 'DRY-RUN'}")
    if not APPLY:
        print("\n검수 후 실제 실행: PYTHONPATH=. uv run python scripts/register_eval0608.py --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
