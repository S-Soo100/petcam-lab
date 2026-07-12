"""R2 clip 다운로드 헬퍼 (임시). r2_key 를 인자로 받아 storage/ 하위에 저장.

버킷=R2_BUCKET(petcam-clips), object key=r2_key 그대로 (nightly-reporter download_clip 동형).
저장 경로 = storage/<camera_dir>/<basename> — 기존 로컬 관례 유지 + donts python#12(영상은 storage/ 안).

사용:
  PYTHONPATH=. uv run python scripts/_download_clip.py <r2_key> [<r2_key> ...]
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

from backend.r2_uploader import get_r2_bucket, get_r2_client

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")


def main() -> int:
    keys = sys.argv[1:]
    if not keys:
        sys.exit("r2_key 를 하나 이상 인자로 넘겨줘")
    cli, bkt = get_r2_client(), get_r2_bucket()
    for key in keys:
        parts = key.split("/")
        cam_dir = parts[-2] if len(parts) >= 2 else "misc"
        dst = REPO / "storage" / cam_dir / parts[-1]
        dst.parent.mkdir(parents=True, exist_ok=True)
        cli.download_file(bkt, key, str(dst))
        mb = dst.stat().st_size / 1_000_000
        print(f"✓ {parts[-1]}  →  storage/{cam_dir}/  ({mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
