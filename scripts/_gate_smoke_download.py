"""gate recall 스모크 — backlog 에서 unseen/moving 몇 개 R2 다운 (임시).

사용:  PYTHONPATH=. uv run python scripts/_gate_smoke_download.py
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
unseen = [r for r in rows if r["action"] == "unseen"][:2]
moving = [r for r in rows if r["action"] == "moving"][:3]
picks = unseen + moving

out = Path("/tmp/gate_smoke")
out.mkdir(parents=True, exist_ok=True)
cli, bkt = get_r2_client(), get_r2_bucket()
for r in picks:
    dst = out / f"{r['clip_id']}.mp4"
    cli.download_file(bkt, r["r2_key"], str(dst))
    print(f"{r['clip_id'][:8]} {r['action']:8s} → {dst.name}")
print(f"다운 완료: {len(picks)}개 → {out}")
