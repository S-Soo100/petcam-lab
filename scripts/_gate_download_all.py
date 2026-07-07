"""gate 검증 — backlog.jsonl 의 clip 전부 R2 다운 (임시, 멱등).

사용:  PYTHONPATH=. uv run python scripts/_gate_download_all.py
이미 받은 파일은 skip → 중단돼도 재실행하면 이어서.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

from backend.r2_uploader import get_r2_bucket, get_r2_client  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")

rows = [json.loads(x) for x in open("/tmp/backlog.jsonl") if x.strip()]
out = Path("/tmp/gate_clips")
out.mkdir(parents=True, exist_ok=True)
cli, bkt = get_r2_client(), get_r2_bucket()

done = skipped = 0
for r in rows:
    dst = out / f"{r['clip_id']}.mp4"
    if dst.exists() and dst.stat().st_size > 0:
        skipped += 1
        done += 1
        continue
    cli.download_file(bkt, r["r2_key"], str(dst))
    done += 1
    if done % 25 == 0:
        print(f"{done}/{len(rows)} (skip {skipped})", flush=True)
print(f"완료 {done}/{len(rows)} (기존 skip {skipped}) → {out}")
