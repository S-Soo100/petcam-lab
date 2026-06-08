"""159건 중 contact-sheet 적합 클래스(109건) 5x6 360px contact sheet — 203 Claude 평가 Step 1.

파일럿(eval-pilot-6x6) 결과: shedding 20%/defecating 0% → contact sheet 부적합 확정.
그래서 적합 5클래스(moving/hand_feeding/eating_prey/drinking/eating_paste)만 평가.
조건은 44건(eval-0608)과 동일한 5x6 360px → 153건 공정 통합.

R2 다운로드 → ffmpeg → experiments/eval-159-claude/sample-{short}/contact.jpg + meta.json.
실행: PYTHONPATH=. uv run python scripts/make_eval159_sheets.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.vlm.gemini_client import download_clip_bytes  # noqa: E402
from scripts.eval_vlm_worker_regression import load_eval_set, load_eval_set_0608  # noqa: E402
from scripts.utils.sheets import make_contact_sheet_from_bytes  # noqa: E402

OUT = REPO / "experiments" / "eval-159-claude"
# contact sheet 적합 클래스 (파일럿서 미세/순간 행동 제외 확정)
ADEQUATE = {"moving", "hand_feeding", "eating_prey", "drinking", "eating_paste"}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    all203 = load_eval_set()
    new44 = {t.clip_id for t in load_eval_set_0608()}
    old159 = [t for t in all203 if t.clip_id not in new44]
    picks = sorted((t for t in old159 if t.gt_action in ADEQUATE), key=lambda x: x.clip_id)
    skipped = [t for t in old159 if t.gt_action not in ADEQUATE]

    print(f"159건 중 적합 {len(picks)}개 (스킵 {len(skipped)}: 미세/순간 행동)")
    print(f"적합 GT 분포: {dict(sorted(Counter(t.gt_action for t in picks).items(), key=lambda x:-x[1]))}")
    print("설정: 5x6 360px (44건 eval-0608 과 동일)\n")

    ok = fail = skip = 0
    for i, t in enumerate(picks, 1):
        short = t.clip_id[:8]
        d = OUT / f"sample-{short}"
        d.mkdir(exist_ok=True)
        sheet = d / "contact.jpg"
        if sheet.exists():
            skip += 1
            continue
        try:
            vb = download_clip_bytes(t.r2_key)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}/{len(picks)}] {short} R2 FAIL: {type(exc).__name__}")
            fail += 1
            continue
        good = make_contact_sheet_from_bytes(vb, sheet, tile="5x6", scale=360)
        (d / "meta.json").write_text(
            json.dumps({"clip_id": t.clip_id, "gt": t.gt_action, "r2_key": t.r2_key},
                       ensure_ascii=False, indent=2)
        )
        if good:
            ok += 1
            if i % 20 == 0:
                print(f"  [{i}/{len(picks)}] ... {ok} ok")
        else:
            fail += 1
            print(f"  [{i}/{len(picks)}] {short} FFMPEG FAIL")
    print(f"\nok={ok} fail={fail} skip={skip}  → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
