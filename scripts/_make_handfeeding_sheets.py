"""임시: hand_feeding 샘플 contact sheet 생성 — Claude 구독 v3.6 OOD 룰 검증용.

experiment-claude-subscription-rba.md 트랙 (방법론 검증, 모델 일반화 X). R2 영상 다운 →
ffmpeg 5x6 격자 contact sheet → experiments/claude-subscription-rba/sample-<short>/contact.jpg.
이후 Claude(이 세션)가 그 이미지를 직접 보고 v3.6 OOD 룰로 판정. 확인 후 삭제 가능 (`_` prefix).

실행: PYTHONPATH=. uv run python scripts/_make_handfeeding_sheets.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.vlm.gemini_client import download_clip_bytes  # noqa: E402

# short -> (r2_key, GT-after-sync). hand_feeding 5 + moving 1(대조군).
CLIPS: dict[str, tuple[str, str]] = {
    "27c5b14f": ("clips/uploaded/2026-04-26/9497d05f-1742-4a77-a156-258a7ece92fb_27c5b14f-05f8-41ec-b26d-527d84ebbfb4.mp4", "hand_feeding"),
    "9af1ba2e": ("clips/uploaded/2026-04-28/9ad72958-5e1c-4d84-a741-9f1ce820db78_9af1ba2e-44ed-4cdd-bffc-b9deae35f5b6.mp4", "hand_feeding"),
    "b8317750": ("clips/uploaded/2026-04-28/10720e4b-ab16-41b6-8a8b-a9f676873812_b8317750-625b-4020-9376-58b0a6c10c2a.mp4", "hand_feeding"),
    "cc0c1d04": ("clips/uploaded/2026-04-26/f1fff0db-21b5-4704-a6d4-30d0597c6da4_cc0c1d04-0a27-4941-985f-4db3bc407b38.mp4", "hand_feeding"),
    "ce5fee73": ("clips/uploaded/2026-04-29/ce5fee73-9f8f-4083-820d-15e1c04af6b9_ce5fee73-9f8f-4083-820d-15e1c04af6b9.mp4", "hand_feeding"),
    "65b57205": ("clips/3a6cffbf-be83-4c77-9fa7-4fcc517c74a6/2026-04-27/020540_motion_65b57205-599f-4021-86fb-3edd2fdb9d14.mp4", "moving"),
}

OUT = REPO / "experiments" / "claude-subscription-rba"


def _duration(path: str) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path]
        ).decode().strip()
        return float(out) if out and out != "N/A" else 30.0
    except Exception:
        return 30.0


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for short, (key, gt) in CLIPS.items():
        d = OUT / f"sample-{short}"
        d.mkdir(exist_ok=True)
        sheet = d / "contact.jpg"
        if sheet.exists():
            print(f"[{short}] exists, skip")
            continue
        try:
            vb = download_clip_bytes(key)
        except Exception as exc:  # noqa: BLE001
            print(f"[{short}] R2 download FAIL: {type(exc).__name__}: {exc}")
            continue
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(vb)
            tmp = f.name
        dur = _duration(tmp)
        # 30프레임 균등 → 5x6 격자. dur 가 짧으면 칸이 빈다(무해).
        fps = max(30.0 / dur, 0.2)
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", tmp, "-vf",
             f"fps={fps:.4f},scale=360:-2,tile=5x6", "-frames:v", "1", str(sheet)],
            capture_output=True,
        )
        ok = sheet.exists()
        print(f"[{short}] GT={gt} dur={dur:.1f}s fps={fps:.3f} -> {'OK' if ok else 'FFMPEG FAIL'}")
        if not ok:
            print("   ffmpeg stderr:", r.stderr.decode()[-300:])
        Path(tmp).unlink(missing_ok=True)

    print(f"\ncontact sheets in: {OUT}")


if __name__ == "__main__":
    main()
