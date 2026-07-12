"""단일 클립 완전 삭제 (R2 파일 + DB row + behavior_logs CASCADE) — 임시.

영구 삭제라 사용자가 직접 실행(assistant 는 되돌릴 수 없는 삭제를 대행하지 않음).
사용:  ! PYTHONPATH=. uv run python scripts/_delete_clip.py <clip_id_full_uuid>
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402
from supabase import create_client  # noqa: E402

from backend.r2_uploader import get_r2_bucket, get_r2_client  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
if len(sys.argv) < 2:
    sys.exit("사용: python scripts/_delete_clip.py <clip_id>")
clip_id = sys.argv[1]

load_dotenv(REPO / ".env")
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

rows = sb.table("camera_clips").select("id, r2_key, source").eq("id", clip_id).execute().data
if not rows:
    sys.exit(f"clip {clip_id} 없음 (이미 삭제됐거나 오타)")
r2_key = rows[0]["r2_key"]
n_logs = len(sb.table("behavior_logs").select("id").eq("clip_id", clip_id).execute().data)
n_labels = len(sb.table("behavior_labels").select("id").eq("clip_id", clip_id).execute().data)
print(f"삭제 대상: {clip_id}  (source={rows[0]['source']})")
print(f"  r2_key      : {r2_key}")
print(f"  behavior_logs   {n_logs}개 (CASCADE 삭제)")
print(f"  behavior_labels {n_labels}개 (CASCADE 삭제)")

if r2_key:
    get_r2_client().delete_object(Bucket=get_r2_bucket(), Key=r2_key)
    print("  → R2 파일 삭제 ✅")
sb.table("camera_clips").delete().eq("id", clip_id).execute()
print("  → camera_clips + behavior_logs/labels(CASCADE) 삭제 ✅")
print("완전 삭제 완료 (되돌리기 불가).")
