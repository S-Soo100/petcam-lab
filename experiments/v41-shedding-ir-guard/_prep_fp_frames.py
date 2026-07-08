"""Set-FP(32) 프레임 준비 — R2 다운로드 + 적응형@1080 추출 + blind meta.

v40-regression 과 동일 입력표현 보장: `_extract_frames_clip.extract_adaptive`
(간격 3.5s / clamp 6~20 / 구간중앙 / no-upscale) 그대로 재사용.

출력: frames-fp/sample-{c8}/f_*.jpg + meta.json({gt,src,c8}) — GT는 meta 에만(blind).
실행: `PYTHONPATH=. uv run python experiments/v41-shedding-ir-guard/_prep_fp_frames.py`
멱등: 프레임 이미 있으면 skip.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent.parent
EXP = Path(__file__).resolve().parent
FRAMES = EXP / "frames-fp"
CLIPS = REPO / "storage" / "v41-fp-clips"

load_dotenv(REPO / ".env")

import sys

sys.path.insert(0, str(REPO))
from backend.r2_uploader import get_r2_bucket, get_r2_client  # noqa: E402
from scripts._extract_frames_clip import extract_adaptive  # noqa: E402


def main() -> None:
    rows = json.loads((EXP / "sample_list_fp.json").read_text())
    cli, bkt = get_r2_client(), get_r2_bucket()
    CLIPS.mkdir(parents=True, exist_ok=True)

    for i, r in enumerate(rows, 1):
        c8 = r["clip_id"][:8]
        out = FRAMES / f"sample-{c8}"
        meta = out / "meta.json"
        if meta.exists() and any(out.glob("f_*.jpg")):
            print(f"[{i:>2}/32] {c8} skip (이미 있음)")
            continue

        key = r["r2_key"]
        local = CLIPS / Path(key).name
        if not local.exists():
            cli.download_file(bkt, key, str(local))

        nf = extract_adaptive(local, out, interval=3.5, lo=6, hi=20)
        meta.write_text(
            json.dumps(
                {"gt": r["gt"], "src": Path(key).name, "c8": c8, "nframes": nf},
                ensure_ascii=False,
            )
        )
        print(f"[{i:>2}/32] {c8} → {nf}프레임")

    dirs = sorted(FRAMES.glob("sample-*"))
    total = sum(len(list(d.glob('f_*.jpg'))) for d in dirs)
    print(f"\nSet-FP 준비 완료: {len(dirs)} samples · {total} frames · avg {total/max(len(dirs),1):.1f}")


if __name__ == "__main__":
    main()
