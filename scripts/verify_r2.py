"""
R2 라운드트립 수동 검증 스크립트 (일회성).

§3-1 완료조건: 1MB 더미 mp4 업로드 → signed URL GET → 다운로드 한 바이트 일치.
실제 storage/ 안에 있는 mp4 파일로 더 현실적으로 테스트.

순서:
1. 로컬 mp4 SHA-256 계산
2. r2_uploader.upload_clip() 으로 R2 업로드 (verify/ 프리픽스, R2 대시보드에서 분리해서 볼 수 있게)
3. generate_signed_url() 로 1h TTL URL 발급
4. urllib 로 URL GET → 받은 바이트 SHA-256 비교
5. delete_object() 로 R2 cleanup (테스트 객체 남기지 말 것)

실행: uv run python scripts/verify_r2.py [optional_mp4_path]
기본 경로 없으면 storage/clips 안에서 가장 최근 mp4 자동 선택.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.r2_uploader import (  # noqa: E402
    generate_signed_url,
    get_r2_bucket,
    get_r2_client,
    upload_clip,
)


def _pick_sample() -> Path:
    """storage/clips/ 에서 100KB+ 인 가장 최근 mp4 자동 선택.
    100KB 미만은 캡처 실패한 stub 일 가능성 (정상 60s 세그먼트는 ~1MB+).
    """
    clips_root = REPO_ROOT / "storage" / "clips"
    candidates = sorted(
        (p for p in clips_root.rglob("*.mp4") if p.stat().st_size >= 100_000),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise SystemExit(f"no mp4 ≥100KB found under {clips_root}")
    return candidates[0]


def _sha256(path_or_bytes: Path | bytes) -> str:
    h = hashlib.sha256()
    if isinstance(path_or_bytes, Path):
        with path_or_bytes.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    else:
        h.update(path_or_bytes)
    return h.hexdigest()


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else _pick_sample()
    if not src.is_file():
        raise SystemExit(f"not a file: {src}")

    src_size = src.stat().st_size
    src_sha = _sha256(src)
    print(f"[1/5] local: {src}")
    print(f"      size={src_size} bytes  sha256={src_sha[:16]}...")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    r2_key = f"verify/{ts}_{src.name}"
    print(f"[2/5] uploading → r2://{get_r2_bucket()}/{r2_key}")
    uploaded = upload_clip(src, r2_key)
    assert uploaded == src_size, f"size mismatch: {uploaded} != {src_size}"

    print("[3/5] issuing signed URL (TTL=3600s)")
    url = generate_signed_url(r2_key, ttl_sec=3600)
    print(f"      {url[:90]}...")

    print("[4/5] GET via urllib")
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        downloaded = resp.read()
    dl_sha = _sha256(downloaded)
    if dl_sha != src_sha:
        raise SystemExit(
            f"FAIL: sha mismatch  local={src_sha}  remote={dl_sha}"
        )
    print(f"      OK — {len(downloaded)} bytes  sha256={dl_sha[:16]}...")

    print(f"[5/5] cleanup: delete r2://{get_r2_bucket()}/{r2_key}")
    get_r2_client().delete_object(Bucket=get_r2_bucket(), Key=r2_key)
    print("      done")
    print("\nALL GREEN — R2 라운드트립 정상")


if __name__ == "__main__":
    main()
