"""eval-0608 44개 contact sheet 생성 — Claude v3.6 정성 평가 입력.

로컬 inbox/0608 영상 → ffmpeg 5x6 격자 contact sheet → experiments/eval-0608-claude/.
이후 Claude(이 세션)가 각 contact.jpg 를 v3.6 프롬프트로 직접 판정한다.
`_make_handfeeding_sheets.py` 의 R2 버전을 로컬 파일용으로 일반화한 것.

⚠️ contact sheet 한계: 30프레임을 360px 격자로 압축 → drinking↔eating_paste 미세
혀 접촉, hand_feeding 미세 도구는 안 보일 수 있음 (experiment-claude-subscription-rba §7).
정량 baseline 이 아니라 정성 스냅샷용.

실행: PYTHONPATH=. uv run python scripts/make_eval0608_sheets.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INBOX = REPO / "inbox" / "0608"
OUT = REPO / "experiments" / "eval-0608-claude"


def gt_from_name(name: str) -> str:
    n = name.lower()
    if n.startswith("not-drinking"):
        return "moving"
    if n.startswith("hand-feeding"):
        return "hand_feeding"
    if n.startswith("eating-paste"):
        return "eating_paste"
    if n.startswith("eating-prey"):
        return "eating_prey"
    if n.startswith("drinking"):
        return "drinking"
    raise ValueError(f"GT 매핑 실패: {name}")


def duration(path: Path) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)]
        ).decode().strip()
        return float(out) if out and out != "N/A" else 30.0
    except Exception:
        return 30.0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    videos = sorted(
        p for p in INBOX.iterdir()
        if p.suffix.lower() in {".mov", ".mp4"} and not p.name.startswith(".")
    )
    print(f"inbox/0608 영상 {len(videos)}개 → contact sheet")
    ok = fail = skip = 0
    for p in videos:
        gt = gt_from_name(p.name)
        d = OUT / f"sample-{p.stem}"
        d.mkdir(exist_ok=True)
        sheet = d / "contact.jpg"
        if sheet.exists():
            print(f"  [skip] {p.name}")
            skip += 1
            continue
        dur = duration(p)
        # 30프레임 균등 → 5x6 격자. 짧으면 칸이 빈다(무해).
        fps = max(30.0 / dur, 0.2)
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(p), "-vf",
             f"fps={fps:.4f},scale=360:-2,tile=5x6", "-frames:v", "1", str(sheet)],
            capture_output=True,
        )
        good = sheet.exists()
        (d / "meta.json").write_text(
            json.dumps(
                {"filename": p.name, "gt": gt, "duration_sec": round(dur, 2)},
                ensure_ascii=False, indent=2,
            )
        )
        print(f"  [{p.stem}] GT={gt} dur={dur:.1f}s -> {'OK' if good else 'FFMPEG FAIL'}")
        if good:
            ok += 1
        else:
            fail += 1
            print("     stderr:", r.stderr.decode()[-200:])
    print(f"\nok={ok} fail={fail} skip={skip}  → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
