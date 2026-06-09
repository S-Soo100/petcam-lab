"""흔들림 완화 탐색 — 폰 핸드헬드 drinking 8건을 ffmpeg deshake 로 "가상 고정 카메라"
로 만들어 raw vs deshaked motion 을 비교한다.

가설: 8건이 motion PoC 에서 신호가 안 보인 건 카메라 흔들림이 global motion 을 오염시켰기
때문. deshake 로 카메라 ego-motion(손떨림)을 빼면 남는 건 게코 고유 움직임 → "몸통 고정 +
머리 좁은 범위 반복 핥기"(sustained lapping)가 살아나는지 본다. = 운영(고정 카메라) 시뮬레이션.

기대: deshake 후 mean_raw 가 내려가면(배경 흔들림 제거됨) + settle 이 길어지고 micro 에
       미세 반복이 남으면 → 흔들림이 진범이었고 고정 카메라면 신호가 있다는 뜻.
한계: deshake 는 translation/rotation 보정. 줌/급격한 각도 변화(확대 케이스)는 약함.

실행: PYTHONPATH=. uv run python experiments/drinking-motion-poc/compare_deshake.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from motion_energy import DATASET, analyze, motion_series  # noqa: E402

# 진짜 drinking 인데 폰 흔들림으로 놓친 8건 (memory: drinking-temporal-poc-data-gap)
CLIPS = ["00c089c8", "f4b33f32", "3369d723", "6a24c2e6",
         "7124cebe", "cf698b78", "d95e9eaa", "bf83c4cf"]
TMP = Path("/tmp/drinking-deshake")


def find_clip(c8: str) -> Path | None:
    m = [p for p in DATASET.glob(f"*{c8}*") if p.suffix.lower() in (".mp4", ".mov")]
    return m[0] if m else None


def deshake(src: Path, c8: str) -> Path | None:
    TMP.mkdir(parents=True, exist_ok=True)
    out = TMP / f"{c8}.mp4"
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-vf", "deshake", "-an", str(out)],
        capture_output=True, text=True,
    )
    return out if (r.returncode == 0 and out.exists()) else None


def main() -> int:
    print(f"\n흔들림 완화 비교 — drinking 8건 (raw → deshaked)\n")
    print(f"{'clip':9s} {'mean(움직임량)':16s} {'micro(미세진동)':16s} {'settle(정착초)':15s}")
    print("-" * 70)
    for c8 in CLIPS:
        src = find_clip(c8)
        if not src:
            print(f"{c8}  MISSING")
            continue
        mr = analyze(motion_series(src))
        dsh = deshake(src, c8)
        if not dsh:
            print(f"{c8}  deshake 실패 (raw mean={mr['mean_raw']:.2f})")
            continue
        md = analyze(motion_series(dsh))
        print(f"{c8:9s} {mr['mean_raw']:5.2f} → {md['mean_raw']:5.2f}      "
              f"{mr['micro']:.2f} → {md['micro']:.2f}       "
              f"{mr['settle_s']:4.1f} → {md['settle_s']:4.1f}")
        print(f"           raw : {mr['spark']}")
        print(f"           desh: {md['spark']}")
    print("\n해석: mean↓ = 카메라 흔들림 제거됨 / settle↑+micro 유지 = 게코 sustained-lapping 잔존")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
