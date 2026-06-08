"""파일럿: 어려운 클래스(shedding/defecating) 6x6 480px contact sheet — 203 전수 전 설정 검증.

목적: 6x6 480px(44건 5x6 360px 보다 조밀) 가 미세행동(허물벗기/배변)을 contact sheet 로
잡는지 + N회 흔들림을 먼저 측정. 효과 확인돼야 203 전수에 6x6 적용.

159건(eval-0608 아닌) 중 shedding 5 + defecating 3 = 8개를 R2 다운로드 → ffmpeg 6x6.
실행: PYTHONPATH=. uv run python scripts/make_pilot_sheets.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.vlm.gemini_client import download_clip_bytes  # noqa: E402
from scripts.eval_vlm_worker_regression import load_eval_set, load_eval_set_0608  # noqa: E402
from scripts.utils.sheets import make_contact_sheet_from_bytes  # noqa: E402

OUT = REPO / "experiments" / "eval-pilot-6x6"
TILE = "6x6"      # 36 프레임 (44건 5x6=30 보다 조밀)
SCALE = 480       # 44건 360 보다 큼


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    all203 = load_eval_set()
    new44 = {t.clip_id for t in load_eval_set_0608()}
    old159 = [t for t in all203 if t.clip_id not in new44]

    by_gt: dict[str, list] = defaultdict(list)
    for t in sorted(old159, key=lambda x: x.clip_id):
        by_gt[t.gt_action].append(t)

    picks = by_gt["shedding"][:5] + by_gt["defecating"][:3]
    print(f"파일럿 {len(picks)}개: shedding {len(by_gt['shedding'][:5])} + defecating {len(by_gt['defecating'][:3])}")
    print(f"설정: tile={TILE} scale={SCALE}px (36프레임)\n")

    ok = fail = 0
    for t in picks:
        short = t.clip_id[:8]
        d = OUT / f"sample-{short}"
        d.mkdir(exist_ok=True)
        sheet = d / "contact.jpg"
        if sheet.exists():
            print(f"  [skip] {short}")
            continue
        try:
            vb = download_clip_bytes(t.r2_key)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{short}] R2 FAIL: {type(exc).__name__}")
            fail += 1
            continue
        good = make_contact_sheet_from_bytes(vb, sheet, tile=TILE, scale=SCALE)
        (d / "meta.json").write_text(
            json.dumps({"clip_id": t.clip_id, "gt": t.gt_action, "r2_key": t.r2_key},
                       ensure_ascii=False, indent=2)
        )
        print(f"  [{short}] GT={t.gt_action:11s} -> {'OK' if good else 'FFMPEG FAIL'}")
        ok += good
        fail += (not good)
    print(f"\nok={ok} fail={fail}  → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
